"""Official piano task with two RM75/L20 Composer entities."""
from dataclasses import dataclass
import numpy as np
from dm_control import mjcf
from dm_control.composer.observation import observable
from dm_control.utils.rewards import tolerance
from note_seq.protobuf import music_pb2
from robopianist.models.hands.base import HandSide
from robopianist.models.hands.rm75_l20 import CHANNELS, RM75L20
from robopianist.music.midi_file import MidiFile
from robopianist.suite.tasks.piano_with_shadow_hands import PianoWithShadowHands

SMOKE_NAME = 'RoboPianist-debug-RM75TwoNotes-v0'

@dataclass(frozen=True)
class RM75MidiFile(MidiFile):
    annotated: bool = False

    def has_fingering(self):
        return self.annotated or any(note.part != 0 for note in self.seq.notes)

    def trim_silence(self):
        return RM75MidiFile(seq=super().trim_silence().seq, annotated=self.has_fingering())

def two_note_midi():
    seq = music_pb2.NoteSequence(total_time=2.0)
    seq.tempos.add(qpm=120)
    seq.notes.add(pitch=55, velocity=80, start_time=.25, end_time=.65, part=6)
    seq.notes.add(pitch=72, velocity=80, start_time=1.05, end_time=1.45, part=1)
    return MidiFile(seq=seq)

def crop_midi(midi, note_offset=0, note_limit=None):
    if note_offset < 0:
        raise ValueError('note_offset must be nonnegative')
    if note_limit is not None and note_limit <= 0:
        raise ValueError('note_limit must be positive')
    if note_offset == 0 and note_limit is None:
        return midi
    ordered = sorted(midi.seq.notes, key=lambda n: (n.start_time, n.end_time, n.pitch, n.part))
    stop = None if note_limit is None else note_offset + note_limit
    selected = ordered[note_offset:stop]
    if not selected:
        raise ValueError('The requested note window is empty')
    seq = music_pb2.NoteSequence()
    seq.CopyFrom(midi.seq)
    del seq.notes[:]
    for note in selected:
        seq.notes.add().CopyFrom(note)
    seq.total_time = max(note.end_time for note in selected)
    return RM75MidiFile(seq=seq, annotated=midi.has_fingering())

class PianoWithRM75L20(PianoWithShadowHands):
    def __init__(self, midi, fingering_margin_m=None, safety_penalty=0.,
                 trailing_silence=0., note_offset=0, note_limit=None,
                 action_mode='full', finger_action_span=32., max_command_step=8.,
                 initial_action=None, fingertip_distance_scale=None,
                 key_press_weight=1., allow_pad_contact=False, **kwargs):
        for key in ('disable_hand_collisions', 'randomize_hand_positions'):
            if kwargs.get(key, False):
                raise ValueError(f'{key} is incompatible with fixed RM75 bases and collision validation')
        if safety_penalty < 0:
            raise ValueError('safety_penalty must be nonnegative')
        if trailing_silence < 0:
            raise ValueError('trailing_silence must be nonnegative')
        self._fingering_margin_m = fingering_margin_m
        self._safety_penalty = float(safety_penalty)
        self._trailing_silence = float(trailing_silence)
        if action_mode not in ('full', 'single_finger'):
            raise ValueError('Unknown action_mode')
        for name, value in (('finger_action_span', finger_action_span),
                            ('max_command_step', max_command_step),
                            ('fingertip_distance_scale', fingertip_distance_scale),
                            ('fingering_margin_m', fingering_margin_m)):
            if value is not None and (not np.isfinite(value) or value <= 0):
                raise ValueError(f'{name} must be finite and positive')
        if fingertip_distance_scale is not None and fingering_margin_m is not None:
            raise ValueError('Choose distance shaping or fingering margin, not both')
        self._action_mode = action_mode
        self._finger_action_span = float(finger_action_span)
        self._max_command_step = float(max_command_step)
        self._fingertip_distance_scale = fingertip_distance_scale
        self._key_press_weight = float(key_press_weight)
        self._allow_pad_contact = bool(allow_pad_contact)
        kwargs.setdefault('physics_timestep', .002)
        kwargs.setdefault('control_timestep', .05)
        kwargs.setdefault('n_steps_lookahead', 10)
        kwargs.setdefault('disable_colorization', True)
        self.termination_reason = None
        self.physical_violations = []
        super().__init__(midi=crop_midi(midi, note_offset, note_limit), **kwargs)
        if initial_action is not None:
            initial_action = np.asarray(initial_action, dtype=float)
            spec = super().action_spec(None)
            if (initial_action.shape != (47,) or not np.isfinite(initial_action).all() or
                    np.any(initial_action < spec.minimum) or np.any(initial_action > spec.maximum) or
                    initial_action[-1] != 0):
                raise ValueError('initial_action must be 47 legal targets with sustain off')
            self.right_hand.home_action = initial_action[:23].copy()
            self.left_hand.home_action = initial_action[23:46].copy()
        self._active_action_indices = np.arange(47)
        if action_mode == 'single_finger':
            if self.midi.n_notes != 1 or self._disable_fingering_reward:
                raise ValueError('single_finger requires exactly one annotated note')
            finger = self.midi.seq.notes[0].part
            if not 0 <= finger < 10:
                raise ValueError('Invalid single-note fingering')
            offset = 0 if finger < 5 else 23
            local_finger = finger % 5
            channels = (0, 5, 10, 15) if local_finger == 0 else (
                local_finger, local_finger+5, local_finger+15)
            self._active_action_indices = np.array([offset+7+CHANNELS.index(c) for c in channels])
            # The rate limiter has state; expose its actual previous targets to the policy.
            applied = observable.Generic(lambda physics: self.applied_action)
            applied.enabled = True
            self._task_observables['applied_action'] = applied
        self.arena.mjcf_model.option.integrator = 'implicitfast'
        self.arena._ground_geom.pos = [0,0,-.7175]
        self.arena._ground_geom.contype = 0
        self.arena._ground_geom.conaffinity = 1
        self.arena._ground_geom.name = 'floor'
        self.arena.mjcf_model.worldbody.add('geom', name='robot_table', type='box', pos=[.805,0,.0075], size=[.4,.875,.025], rgba=[.3,.3,.32,1], contype=0, conaffinity=1)
        self.arena.mjcf_model.statistic.center = [.3,0,.25]
        self.arena.mjcf_model.statistic.extent = 1.6
        self.arena.mjcf_model.worldbody.add('camera', name='rm75_overview', pos=[1.9,-1.9,1.3], xyaxes=[.707,.707,0,-.34,.34,.877])
        for hand in (self.right_hand, self.left_hand):
            for name in ('joints_vel','wrist_position','fingertip_positions'):
                getattr(hand.observables, name).enabled = True
        # The applied_action observable may be read before the first reset.
        self._last_applied_action = self.home_action.copy()

    def _add_hand(self, hand_side, **kwargs):
        hand = RM75L20(side=hand_side)
        hand.root_body.pos = [.505, .27 if hand_side == HandSide.RIGHT else -.27, .0425]
        hand.root_body.euler = None
        hand.root_body.quat = [2**-.5,0,0,2**-.5]
        # Match gravity compensation in the existing static5 scene builder.
        for body in hand.mjcf_model.find_all('body'):
            body.gravcomp = 1
        self.arena.attach(hand)
        return hand

    def _colorize_fingertips(self):
        pass  # L20 mesh materials are preserved.

    def _reset_trajectory(self):
        super()._reset_trajectory()
        duration = self._initial_buffer_time + self._midi.duration + self._trailing_silence
        count = int(np.ceil(duration / self.control_timestep))
        self._notes = self._notes[:count]
        self._sustains = self._sustains[:count]
        while len(self._notes) < count:
            self._notes.append([])
            self._sustains.append(0)

    def initialize_episode(self, physics, random_state):
        super().initialize_episode(physics, random_state)
        self.termination_reason = None
        self.physical_violations = []
        self._violation_keys = set()
        self._step_violations = 0
        self._step_collision = False
        self._step_joint_limit = False
        self._step_max_penetration_m = 0.
        self.collision_frames = 0
        self.joint_limit_frames = 0
        self.max_penetration_m = 0.
        self.joint_limit_step_counts = {}
        self.collision_pair_step_counts = {}
        self._last_applied_action = self.home_action.copy()
        self._step_joint_names = set()
        self._step_contact_pairs = set()
        self._robot_geom_ids = set()
        self._tip_geom_ids = set()
        for hand in (self.right_hand,self.left_hand):
            self._robot_geom_ids.update(physics.bind(hand.collision_geoms).element_id.tolist())
            self._tip_geom_ids.update(physics.bind(hand.tip_geoms).element_id.tolist())
        self._key_geom_ids = set(physics.bind([k.geom[0] for k in self.piano.keys]).element_id.tolist())
        self._pad_geom_ids = set()
        self._target_key_geom_id = None
        if self._action_mode == 'single_finger' and self._allow_pad_contact:
            finger = self.midi.seq.notes[0].part
            fname = ('thumb', 'index', 'middle', 'ring', 'little')[finger % 5]
            hand = self.right_hand if finger < 5 else self.left_hand
            pads = [g for g in hand.collision_geoms
                    if g.mesh is not None and g.mesh.name in
                    (f'l20_{fname}_link3', f'l20_{fname}_link4', f'l20_{fname}_link5')]
            self._pad_geom_ids = set(physics.bind(pads).element_id.tolist())
            self._target_key_geom_id = int(physics.bind(
                self.piano.keys[self.midi.seq.notes[0].pitch - 21].geom[0]).element_id)

    @property
    def home_action(self):
        return np.r_[self.right_hand.home_action,self.left_hand.home_action,0.]

    def action_spec(self, physics):
        spec = super().action_spec(physics)
        if self._action_mode == 'full':
            return spec
        lo, hi = spec.minimum.copy(), spec.maximum.copy()
        indices = self._active_action_indices
        lo[indices] = np.maximum(lo[indices], self.home_action[indices]-self._finger_action_span)
        hi[indices] = np.minimum(hi[indices], self.home_action[indices]+self._finger_action_span)
        return spec.replace(minimum=lo, maximum=hi)

    @property
    def applied_action(self):
        return self._last_applied_action.copy()

    def before_step(self, physics, action, random_state):
        if np.asarray(action).shape != (47,) or not np.isfinite(action).all():
            raise ValueError('Expected 47 finite actions')
        if not 0 <= action[-1] <= 1:
            raise ValueError('Sustain outside [0,1]')
        self._step_violations = 0
        self._step_collision = False
        self._step_joint_limit = False
        self._step_max_penetration_m = 0.
        self._step_joint_names = set()
        self._step_contact_pairs = set()
        if self._action_mode == 'single_finger':
            spec = self.action_spec(physics)
            requested = np.clip(action, spec.minimum, spec.maximum)
            action = self.home_action.copy()
            indices = self._active_action_indices
            action[indices] = self._last_applied_action[indices] + np.clip(
                requested[indices]-self._last_applied_action[indices],
                -self._max_command_step, self._max_command_step)
        self._last_applied_action = np.asarray(action).copy()
        super().before_step(physics, action, random_state)

    def collision_violations(self, physics):
        violations = []
        for contact in physics.data.contact:
            a,b = int(contact.geom1),int(contact.geom2)
            if contact.dist >= -.0001 or not ({a,b} & self._robot_geom_ids):
                continue
            if (a in self._tip_geom_ids and b in self._key_geom_ids) or (b in self._tip_geom_ids and a in self._key_geom_ids):
                continue
            if self._allow_pad_contact and self._target_key_geom_id is not None:
                if (a in self._pad_geom_ids and b == self._target_key_geom_id) or (b in self._pad_geom_ids and a == self._target_key_geom_id):
                    continue
            violations.append({'kind':'collision','geoms':[physics.model.id2name(a,'geom'),physics.model.id2name(b,'geom')], 'penetration_m':float(-contact.dist)})
        return violations

    def joint_limit_violations(self, physics):
        violations = []
        for hand in (self.right_hand,self.left_hand):
            q = physics.bind(hand.joints).qpos
            limits = np.asarray([j.range for j in hand.joints])
            bad = np.flatnonzero((q < limits[:,0]-.02) | (q > limits[:,1]+.02))
            if len(bad):
                violations.append({'kind':'joint_limit','joints':[hand.joints[i].full_identifier for i in bad]})
        return violations

    def after_substep(self, physics, random_state):
        for violation in self.collision_violations(physics)+self.joint_limit_violations(physics):
            self._step_violations += 1
            if violation['kind'] == 'collision':
                self._step_collision = True
                self._step_contact_pairs.add(' | '.join(sorted(violation['geoms'])))
                self._step_max_penetration_m = max(self._step_max_penetration_m, violation['penetration_m'])
            else:
                self._step_joint_limit = True
                self._step_joint_names.update(violation['joints'])
            names = violation.get('geoms') or violation.get('joints')
            key = (violation['kind'], tuple(str(n) for n in names))
            if key not in self._violation_keys:
                self._violation_keys.add(key)
                self.physical_violations.append(violation)

    def after_step(self, physics, random_state):
        super().after_step(physics, random_state)
        self.collision_frames += int(self._step_collision)
        self.joint_limit_frames += int(self._step_joint_limit)
        self.max_penetration_m = max(self.max_penetration_m, self._step_max_penetration_m)
        for name in self._step_joint_names:
            self.joint_limit_step_counts[name] = self.joint_limit_step_counts.get(name, 0)+1
        for pair in self._step_contact_pairs:
            self.collision_pair_step_counts[pair] = self.collision_pair_step_counts.get(pair, 0)+1

    def step_safety_metrics(self):
        return {
            'collision': self._step_collision,
            'joint_limit': self._step_joint_limit,
            'max_penetration_m': self._step_max_penetration_m,
        }

    def safety_metrics(self):
        return {
            'collision_frames': self.collision_frames,
            'joint_limit_frames': self.joint_limit_frames,
            'max_penetration_m': self.max_penetration_m,
            'joint_limit_step_counts': dict(self.joint_limit_step_counts),
            'collision_pair_step_counts': dict(self.collision_pair_step_counts),
        }

    def reward_components(self, physics):
        components = {
            'key_press_reward': float(self._compute_key_press_reward(physics)),
            'sustain_reward': float(self._compute_sustain_reward(physics)),
            'energy_reward': float(self._compute_energy_reward(physics)),
        }
        fingering_name = 'fingering_reward' if not self._disable_fingering_reward else 'ot_fingering_reward'
        components[fingering_name] = float(getattr(self, '_compute_'+fingering_name)(physics))
        if not self._disable_forearm_reward:
            components['forearm_reward'] = float(self._compute_forearm_reward(physics))
        return components

    def should_terminate_episode(self, physics):
        ended = super().should_terminate_episode(physics)
        if ended:
            self.termination_reason = 'score_complete' if self._should_terminate else 'wrong_press'
        return ended

    def _compute_key_press_reward(self, physics):
        return self._key_press_weight * super()._compute_key_press_reward(physics)

    def _compute_forearm_reward(self, physics):
        return -self._safety_penalty if self._step_violations else .5

    def _compute_fingering_reward(self, physics):
        if self._fingertip_distance_scale is not None:
            distances = [row['distance_m'] for row in self.fingertip_diagnostics(physics)]
            if not distances:
                return 0.
            # Bounded, monotone approach feedback without the Gaussian's near-zero tail.
            return float(np.mean(1/(1+np.asarray(distances)/self._fingertip_distance_scale)))
        if self._fingering_margin_m is None:
            return super()._compute_fingering_reward(physics)
        margin = self._fingering_margin_m

        def distances(hand_keys, hand):
            out = []
            for key, finger in hand_keys:
                tip = physics.bind(hand.fingertip_sites[finger]).xpos.copy()
                geom = self.piano.keys[key].geom[0]
                key_pos = physics.bind(geom).xpos.copy()
                key_pos[-1] += .5*physics.bind(geom).size[2]
                key_pos[0] += .35*physics.bind(geom).size[0]
                out.append(float(np.linalg.norm(key_pos-tip)))
            return out

        d = distances(self._rh_keys_current, self.right_hand)+distances(self._lh_keys_current, self.left_hand)
        if not d:
            return 0.
        return float(np.mean(tolerance(np.hstack(d), bounds=(0, margin), margin=margin*10, sigmoid='gaussian')))

    def fingertip_diagnostics(self, physics):
        rows = []
        for side, hand, keys in (('right', self.right_hand, self._rh_keys_current),
                                 ('left', self.left_hand, self._lh_keys_current)):
            for key, finger in keys:
                tip = physics.bind(hand.fingertip_sites[finger]).xpos.copy()
                geom = physics.bind(self.piano.keys[key].geom[0])
                target = geom.xpos.copy()
                target[-1] += .5*geom.size[2]
                target[0] += .35*geom.size[0]
                rows.append({'side':side, 'finger':int(finger), 'pitch':int(key+21),
                             'distance_m':float(np.linalg.norm(tip-target)),
                             'tip_position':tip.tolist(), 'target_position':target.tolist()})
        return rows
