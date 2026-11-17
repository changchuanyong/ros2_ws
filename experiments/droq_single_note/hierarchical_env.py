"""Hierarchical RL task for T-0055: policy outputs target key angle (press depth)
every 50 ms; a 1 kHz inner loop does key_surface(qdes) + IK + force/impedance
feedback. Extends the frozen PianoWithRM75L20 without modifying it.

Action: 1-dim target key angle qdes in [0, angle_max] (press depth). The inner
loop holds qdes for the 50 ms control step and generates arm ctrl from LIVE
feedback at 1 kHz (no recorded ctrl replay). Observation/reward are the task's
standard ones. Corrected contact baseline applied by the caller.
"""
import numpy as np
from dm_control import mjcf
from dm_control.composer.observation import observable
from dm_env import specs
from scipy.spatial.transform import Rotation

from robopianist.suite.tasks.piano_with_rm75_l20 import PianoWithRM75L20

KEY = 51
ANGLE_MAX = .064


def smooth(value):
    x = np.clip(value, 0., 1.)
    return x * x * (3. - 2. * x)


class HierarchicalPianoTask(PianoWithRM75L20):
    def __init__(self, *args, angle_max=ANGLE_MAX, normal_force=1.35, force_gain=2.,
                 force_damping=40., frequency=50., depth=.00015, feedback=.08,
                 key_damping=.0005, x_offset=.03, **kwargs):
        kwargs['action_mode'] = 'full'
        super().__init__(*args, **kwargs)
        self._angle_max = float(angle_max)
        self._normal_force = float(normal_force)
        self._force_gain = float(force_gain)
        self._force_damping = float(force_damping)
        self._frequency = float(frequency)
        self._depth = float(depth)
        self._feedback = float(feedback)
        self._key_damping = float(key_damping)
        self._x_offset = float(x_offset)
        self._policy_qdes = 0.
        self._inner_initialized = False

    def action_spec(self, physics):
        return specs.BoundedArray((1,), np.float64, 0., self._angle_max, name='target_key_angle')

    def _init_inner(self, ph):
        hand = self.right_hand
        self._hand = hand
        self._kin = ph.copy(share_model=True)
        self._site = int(ph.bind(hand.fingertip_sites[1]).element_id)
        self._key_geom = int(ph.bind(self.piano.keys[KEY].geom[0]).element_id)
        self._arm_q = np.asarray(ph.bind(hand.joints[:7]).qposadr, dtype=int)
        self._arm_d = np.asarray(ph.bind(hand.joints[:7]).dofadr, dtype=int)
        self._key_q = int(ph.bind(self.piano.joints[KEY]).qposadr)
        self._key_d = int(ph.bind(self.piano.joints[KEY]).dofadr)
        self._limit = ph.bind(hand.joints[:7]).range.copy()
        self._rot0 = ph.data.site_xmat[self._site].reshape(3, 3).copy()
        self._home_tip = ph.data.site_xpos[self._site].copy()
        gid = int(ph.bind(hand.mjcf_model.find('geom', 'right_collision_22')).element_id)
        mid = ph.model.geom_dataid[gid]
        s, c = ph.model.mesh_vertadr[mid], ph.model.mesh_vertnum[mid]
        verts = ph.model.mesh_vert[s:s+c].astype(float)
        pts = verts @ ph.data.geom_xmat[gid].reshape(3, 3).T + ph.data.geom_xpos[gid]
        self._support = (pts[np.argmin(pts[:, 2])] - self._home_tip) @ self._rot0
        self._pad_geom = gid
        self._qref = ph.data.qpos[self._arm_q].copy()
        self._nominal_qpos = ph.data.qpos.copy()
        self._jacp = np.zeros((3, ph.model.nv)); self._jacr = np.zeros((3, ph.model.nv))
        self._mass = np.zeros((ph.model.nv, ph.model.nv))
        self._arm_act = np.asarray(ph.bind(hand.actuators[:7]).element_id, dtype=int)
        self._z_integral = 0.; self._filtered_force = 0.
        self._prev_ref = self._qref.copy(); self._prev_ref_vel = np.zeros(7)
        self._inner_initialized = True

    def _key_surface(self, angle):
        self._kin.data.qpos[self._key_q] = angle
        mjcf_kinematics(self._kin)
        rot = self._kin.data.geom_xmat[self._key_geom].reshape(3, 3)
        size = self._kin.model.geom_size[self._key_geom]
        return self._kin.data.geom_xpos[self._key_geom] + rot @ np.array([.35*size[0]+self._x_offset, 0., size[2]])

    def initialize_episode(self, physics, random_state):
        super().initialize_episode(physics, random_state)
        self._policy_qdes = 0.
        self._inner_initialized = False

    def before_step(self, physics, action, random_state):
        a = np.asarray(action, dtype=float).reshape(-1)
        self._policy_qdes = float(np.clip(a[0], 0., self._angle_max))
        # Apply home posture through the base; the inner loop overrides arm ctrl.
        super().before_step(physics, self.home_action, random_state)

    def before_substep(self, physics, action, random_state):
        super().before_substep(physics, action, random_state)
        ph = physics
        if not self._inner_initialized:
            self._init_inner(ph)
        dt = float(ph.model.opt.timestep)
        t = float(ph.data.time)
        qdes = self._policy_qdes
        press_frac = smooth(qdes / .02)
        gap = .006 * (1 - press_frac) + .00015 * press_frac
        rot = Rotation.from_euler('y', qdes).as_matrix() @ self._rot0
        q = float(ph.data.qpos[self._key_q]); qvel = float(ph.data.qvel[self._key_d])
        if qdes > .02 and self._feedback:
            self._z_integral = float(np.clip(self._z_integral - self._feedback*(qdes-q)*dt, -.002, .002))
        else:
            self._z_integral *= .95
        correction = self._z_integral + (self._key_damping*qvel if qdes > .02 else 0.)
        target = self._key_surface(qdes) - rot @ self._support + [0., 0., gap-self._depth+correction]
        self._kin.data.qpos[:] = self._nominal_qpos
        self._kin.data.qpos[self._arm_q] = self._qref
        import mujoco
        for _ in range(6):
            mujoco.mj_kinematics(self._kin.model.ptr, self._kin.data.ptr)
            mujoco.mj_comPos(self._kin.model.ptr, self._kin.data.ptr)
            current = self._kin.data.site_xpos[self._site]
            rot_cur = self._kin.data.site_xmat[self._site].reshape(3, 3)
            err = np.r_[target-current, .08*Rotation.from_matrix(rot@rot_cur.T).as_rotvec()]
            if np.linalg.norm(err) < 1e-6:
                break
            mujoco.mj_jacSite(self._kin.model.ptr, self._kin.data.ptr, self._jacp, self._jacr, self._site)
            jac = np.vstack((self._jacp[:, self._arm_d], .08*self._jacr[:, self._arm_d]))
            delta = jac.T @ np.linalg.solve(jac@jac.T + np.eye(6)*1e-7, err)
            self._kin.data.qpos[self._arm_q] = np.clip(
                self._kin.data.qpos[self._arm_q] + np.clip(delta, -.01, .01),
                self._limit[:, 0]+.002, self._limit[:, 1]-.002)
        self._qref = self._kin.data.qpos[self._arm_q].copy()
        ref_vel = (self._qref - self._prev_ref) / dt
        normal_force = 0.
        for ci, contact in enumerate(ph.data.contact):
            if {contact.geom1, contact.geom2} == {self._pad_geom, self._key_geom}:
                wrench = np.zeros(6); mujoco.mj_contactForce(ph.model.ptr, ph.data.ptr, ci, wrench)
                normal_force += max(0., float(wrench[0]))
        self._filtered_force += dt/(.004+dt)*(normal_force - self._filtered_force)
        force_phase = self._normal_force > 0 and qdes > .02
        desired_force = .2 + (self._normal_force-.2)*press_frac
        mujoco.mj_fullM(ph.model.ptr, self._mass, ph.data.qM)
        accel = self._frequency**2*(self._qref - ph.data.qpos[self._arm_q]) - 2*self._frequency*ph.data.qvel[self._arm_d]
        if force_phase:
            mujoco.mj_jacSite(ph.model.ptr, ph.data.ptr, self._jacp, self._jacr, self._site)
            jac = np.vstack((self._jacp[:, self._arm_d], self._jacr[:, self._arm_d]))
            velocity = np.r_[self._jacp@ph.data.qvel, self._jacr@ph.data.qvel]
            error = np.r_[target - ph.data.site_xpos[self._site],
                          Rotation.from_matrix(rot@ph.data.site_xmat[self._site].reshape(3, 3).T).as_rotvec()]
            cart_accel = self._frequency**2*error - 2*self._frequency*velocity
            cart_accel[2] = -self._force_gain*(desired_force - self._filtered_force) - self._force_damping*velocity[2]
            accel = jac.T @ np.linalg.solve(jac@jac.T + np.eye(6)*1e-7, cart_accel)
        torque = (self._mass[np.ix_(self._arm_d, self._arm_d)]@accel
                  + ph.data.qfrc_bias[self._arm_d] - ph.data.qfrc_passive[self._arm_d])
        if force_phase:
            torque -= self._jacp[:, self._arm_d].T @ np.array([0., 0., desired_force])
        gain = ph.model.actuator_gainprm[self._arm_act, 0]
        bias = ph.model.actuator_biasprm[self._arm_act]
        ctrl = (torque - bias[:, 0] - bias[:, 1]*ph.data.qpos[self._arm_q]
                - bias[:, 2]*ph.data.qvel[self._arm_d]) / gain
        ctrl = np.clip(ctrl, self._limit[:, 0], self._limit[:, 1])
        ph.bind(self._hand.actuators[:7]).ctrl = ctrl
        self._prev_ref = self._qref.copy(); self._prev_ref_vel = ref_vel.copy()


def mjcf_kinematics(kin):
    import mujoco
    mujoco.mj_kinematics(kin.model.ptr, kin.data.ptr)