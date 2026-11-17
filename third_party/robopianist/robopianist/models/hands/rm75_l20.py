"""Composer entity for one RM75-6FB-V and its 16-channel L20 hand."""
from pathlib import Path
import numpy as np
from dm_control import composer, mjcf
from dm_control.composer.observation import observable
from dm_env import specs
from robopianist.models.hands import base, rm75_l20_mapping as mapping

CHANNELS = tuple(range(11)) + tuple(range(15, 20))
HOME = {
    'left': [-2.059087, -1.621110, 2.750937, 1.994508, 2.612697, 2.155555, -3.027617],
    'right': [-0.994662, -1.596130, .408762, -1.923178, -2.532935, -2.094146, -.131761],
}
READY = {
    'right': [-1.011130679851,-1.484745607917,.445652724772,-2.026658941047,-2.501629474414,-2.102685514444,-.154835429283],
    'left': [-2.04327635249,-1.510391637983,2.712050624865,2.101541868569,2.58078904786,2.165643227639,-3.0056805792],
}
FINGERS = ('thumb', 'index', 'middle', 'ring', 'little')

class RM75L20(base.Hand):
    def _build(self, side=base.HandSide.RIGHT):
        self._side = side
        self.side_name = 'right' if side == base.HandSide.RIGHT else 'left'
        prefix = self.side_name + '_'
        model_file = Path(__file__).with_name('third_party') / 'rm75_l20' / f'{self.side_name}.xml'
        if (model_file.parent / 'meshes').is_dir():
            self._model = mjcf.from_path(str(model_file))
        else:
            # ros2_ws modification: resolve the unchanged meshdir from the workspace.
            workspace = Path(__file__).resolve().parents[5]
            model_dir = workspace / 'src/ros2_rm_robot/rm_mujoco'
            self._model = mjcf.from_xml_string(model_file.read_bytes(), model_dir=str(model_dir))
        self._root = self._model.find('body', prefix+'base_link')
        self._joints = [self._model.find('joint', prefix+f'joint{i}') for i in range(1,8)]
        self._joints += [self._model.find('joint', prefix+n) for n in mapping.HAND_JOINT_SUFFIXES]
        self._actuators = [self._model.find('actuator', prefix+f'joint{i}') for i in range(1,8)]
        self._actuators += [next(a for a in self._model.find_all('actuator') if a.joint == j) for j in self._joints[7:]]
        self._command_min = np.zeros(20)
        self._command_max = np.full(20,255.)
        # Intersect protocol range with every driven joint and servo range. In the
        # imported mapping the first two thumb channels exceed their MJCF limits.
        # Keep channel ownership/coupling unchanged, restrict legal commands.
        for joint_index, channel in mapping.JOINT_MAP.items():
            joint = self._joints[7+joint_index]
            actuator = self._actuators[7+joint_index]
            lo = max(joint.range[0], actuator.ctrlrange[0], mapping.RANGE_MIN[channel])
            hi = min(joint.range[1], actuator.ctrlrange[1], mapping.RANGE_MAX[channel])
            values = (np.array([lo,hi])-mapping.RANGE_MIN[channel])*255/(mapping.RANGE_MAX[channel]-mapping.RANGE_MIN[channel])
            if mapping.REVERSE[channel] == -1:
                values = 255-values
            self._command_min[channel] = max(self._command_min[channel],values.min())
            self._command_max[channel] = min(self._command_max[channel],values.max())
        self._tips = [self._model.find('site', prefix+f+'_tip') for f in FINGERS]
        self.wrist = self._model.find('body', prefix+'l20_base_link')
        # The imported palm is a single non-convex CAD shell. Its convex collision
        # hull overlaps the finger mechanisms. Exclude only internal L20 body pairs;
        # all these geoms still collide with either arm, the opposite hand and piano.
        hand_bodies = [self.wrist] + list(self.wrist.find_all('body'))
        for i, first in enumerate(hand_bodies):
            for second in hand_bodies[i+1:]:
                self._model.contact.add('exclude', body1=first, body2=second)
        self.collision_geoms = tuple(self._model.find_all('geom'))
        self.tip_geoms = tuple(g for g in self.collision_geoms if g.mesh is not None and g.mesh.name in [f'l20_{f}_link{5 if f=="thumb" else 4}' for f in FINGERS])
        # Existing right_hand_piano_sim.yaml READY pose, shared protocol on both sides.
        commands = np.array([142,198,197,197,196,251,93,127,129,93,126,0,0,0,0,131,100,101,102,103], dtype=float)
        commands = np.clip(commands,self._command_min,self._command_max)
        # 3 cm wrist lift from static_pose_reference.yaml, orientation held by IK.
        self.home_action = np.r_[READY[self.side_name], commands[list(CHANNELS)]]

    @property
    def mjcf_model(self): return self._model
    @property
    def name(self): return self._model.model
    @property
    def hand_side(self): return self._side
    @property
    def root_body(self): return self._root
    @property
    def joints(self): return tuple(self._joints)
    @property
    def actuators(self): return tuple(self._actuators)
    @property
    def fingertip_sites(self): return tuple(self._tips)

    def _build_observables(self): return RM75L20Observables(self)

    def action_spec(self, physics):
        ranges = np.array([j.range for j in self.joints[:7]])
        return specs.BoundedArray((23,), np.float64, np.r_[ranges[:,0],self._command_min[list(CHANNELS)]], np.r_[ranges[:,1],self._command_max[list(CHANNELS)]], name='\t'.join([self.side_name+f'_joint{i}' for i in range(1,8)]+[self.side_name+f'_l20_{i}' for i in CHANNELS]))

    def targets(self, action):
        action = np.asarray(action, dtype=np.float64)
        if action.shape != (23,) or not np.isfinite(action).all():
            raise ValueError('Expected 23 finite joint/channel targets')
        spec = self.action_spec(None)
        if np.any(action < spec.minimum-1e-5) or np.any(action > spec.maximum+1e-5):
            raise ValueError('RM75/L20 action outside command limits')
        action = np.clip(action,spec.minimum,spec.maximum)
        command = np.zeros(20)
        command[list(CHANNELS)] = action[7:]
        return np.r_[action[:7], mapping.command_positions(command)]

    def apply_action(self, physics, action, random_state=None):
        physics.bind(self.actuators).ctrl = self.targets(action)

    def initialize_episode(self, physics, random_state):
        physics.bind(self.joints).qpos = self.targets(self.home_action)
        physics.bind(self.joints).qvel = 0
        self.apply_action(physics, self.home_action)

class RM75L20Observables(base.HandObservables):
    @composer.observable
    def wrist_position(self): return observable.MJCFFeature('xpos', self._entity.wrist)
    @composer.observable
    def fingertip_positions(self):
        return observable.Generic(lambda physics: physics.bind(self._entity.fingertip_sites).xpos.ravel())
    @composer.observable
    def actuators_power(self):
        return observable.Generic(lambda physics: np.abs(physics.bind(self._entity.actuators).force * physics.bind(self._entity.actuators).velocity))
