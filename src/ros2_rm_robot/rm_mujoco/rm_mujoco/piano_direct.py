"""Reference-free direct hand control for PianoVAM tasks.

The RM75 arms are fixed at the verified high-elbow home pose.  The policy only
changes the twenty L20 ROOT/TIP command channels.  This module deliberately does
not use a performance plan, replay runner, arm tracks or nominal states.
"""

from collections import Counter
import math
from pathlib import Path

import gymnasium as gym
import mujoco as m
import numpy as np
import yaml

from .fingering import PianoHandModel
from .keyboard import KEY_NOTES, KeyEvents, key_site_name
from .l20_joint_mapping import HAND_JOINT_SUFFIXES
from .performance import FINGERS
from .performance_runtime import KeyTravelMonitor
from .pianovam_corpus import PianoVamCorpus
from .pianovam_tasks import HAND_ORDER, load_task_set
from .piano_direct_eval import evaluate_edges
from .piano_direct_reward import DirectReward
from .piano_rl import (
    ACTION_CHANNELS,
    LOOKAHEAD_SEC,
    active_fingers,
    finger_clock,
    target_keys,
)

OBSERVATION_SIZE = 777
DEFAULT_SCENE = "config/piano_scene_static5.yaml"
DEFAULT_HOME = "config/static_pose_reference.yaml"
DEFAULT_POSE = "config/right_hand_piano_sim.yaml"
DEFAULT_CONFIG = "config/piano_direct_env.yaml"


def _resolve(package, value):
    path = Path(value)
    return path if path.is_absolute() else Path(package) / path


class PianoDirectEnv(gym.Env):
    """Fixed-arm, direct L20 control over a `piano_rl_tasks/1` task."""

    metadata = {"render_modes": []}

    def __init__(self, task_path, package, *, task_index=0,
                 active_hands=("left", "right"), control_dt=0.02,
                 scene_config=None, home_pose=None, pose_file=None,
                 action_scale=8.0, ready_curl=None,
                 lookahead_sec=LOOKAHEAD_SEC, reward_weights=None,
                 active_channels=None, observation_lead_sec=0.0,
                 task_indices=None, initial_jitter=0.0):
        super().__init__()
        if not np.isfinite(control_dt) or control_dt <= 0:
            raise ValueError("control_dt must be finite and positive")
        if not np.isfinite(action_scale) or action_scale <= 0:
            raise ValueError("action_scale must be finite and positive")
        if not active_hands or any(side not in HAND_ORDER for side in active_hands):
            raise ValueError("active_hands must contain left and/or right")
        if len(set(active_hands)) != len(active_hands):
            raise ValueError("active_hands must not contain duplicates")
        self.package = Path(package).resolve()
        if isinstance(task_path, PianoVamCorpus):
            self.task_path = None
            self.task_set = task_path
        else:
            self.task_path = Path(task_path).resolve()
            self.task_set = load_task_set(self.task_path)
        self._recording_order = []
        self.recording_resets = Counter()
        if not self.task_set.tasks:
            raise ValueError("task file contains no tasks")
        if not 0 <= int(task_index) < self.task_set.task_count:
            raise ValueError("task_index outside the task set")
        self.task_index = int(task_index)
        self.task = self.task_set.tasks[self.task_index]
        self.task_indices = tuple(task_indices) if task_indices is not None else ()
        if any(not 0 <= index < self.task_set.task_count for index in self.task_indices):
            raise ValueError("task_indices outside the task set")
        if not np.isfinite(initial_jitter) or not 0.0 <= initial_jitter <= 1.0:
            raise ValueError("initial_jitter must be between 0 and 1 L20 command units")
        self.initial_jitter = float(initial_jitter)
        self.active_hands = tuple(active_hands)
        self.control_dt = float(control_dt)
        self.action_scale = float(action_scale)
        self.lookahead_sec = tuple(float(value) for value in lookahead_sec)
        if not self.lookahead_sec or self.lookahead_sec[0] != 0.0:
            raise ValueError("lookahead_sec must start at 0")
        if any(b <= a for a, b in zip(self.lookahead_sec, self.lookahead_sec[1:])):
            raise ValueError("lookahead_sec must increase")
        if not np.isfinite(observation_lead_sec) or observation_lead_sec < 0:
            raise ValueError("observation_lead_sec must be finite and non-negative")
        self.observation_lead_sec = float(observation_lead_sec)
        scene = _resolve(self.package, scene_config or DEFAULT_SCENE)
        home_path = _resolve(self.package, home_pose or DEFAULT_HOME)
        pose_path = _resolve(self.package, pose_file or DEFAULT_POSE)
        home = yaml.safe_load(home_path.read_text(encoding="utf-8"))
        if not isinstance(home, dict) or not isinstance(home.get("arms"), dict):
            raise ValueError("home pose must contain an arms mapping")
        self.home_q = {}
        for side in HAND_ORDER:
            values = home["arms"].get(side, {}).get("joints_rad")
            if not isinstance(values, list) or len(values) != 7:
                raise ValueError(f"home pose {side} must contain seven joint angles")
            self.home_q[side] = np.asarray(values, dtype=float)
        playing = home.get("playing") or {}
        if ready_curl is None:
            ready_curl = playing.get("ready_hand_curl", 0.25)
        if not np.isfinite(ready_curl) or not 0.0 <= ready_curl <= 1.0:
            raise ValueError("ready_curl must be in [0, 1]")
        self.ready_curl = float(ready_curl)
        self.hand_model = PianoHandModel(self.package, scene, pose_path)
        self.model = self.hand_model.model
        self.data = m.MjData(self.model)
        self.key_id = self.model.key("piano_ready").id
        self.substeps = int(round(self.control_dt / self.model.opt.timestep))
        if self.substeps < 1 or abs(
                self.substeps * self.model.opt.timestep - self.control_dt) > 1e-9:
            self.hand_model.tmp.cleanup()
            raise ValueError("control_dt must be a positive multiple of the MuJoCo timestep")
        self.piano_site = self.model.site("piano_frame").id
        self.key_qpos = np.array([self.hand_model.key_qpos[note] for note in KEY_NOTES])
        self.key_limits = np.array([self.hand_model.key_limit[note] for note in KEY_NOTES])
        self.key_sites = {
            note: self.model.site(key_site_name(note)).id for note in KEY_NOTES}
        self.fingertips = self.hand_model.fingertip
        self.reward_model = DirectReward(reward_weights)
        self.hand_dof = {}
        for side in HAND_ORDER:
            joints = [self.model.joint(f"{side}_{suffix}")
                      for suffix in HAND_JOINT_SUFFIXES]
            self.hand_dof[side] = np.array([int(joint.dofadr[0]) for joint in joints])
        self.action_space = gym.spaces.Box(-1.0, 1.0, (20,), np.float32)
        self.action_mask = np.repeat(
            [side in self.active_hands for side in HAND_ORDER], 10).astype(np.float32)
        if active_channels is None:
            active_channels = range(20)
        active_channels = tuple(int(index) for index in active_channels)
        if not active_channels or any(not 0 <= index < 20 for index in active_channels):
            raise ValueError("active_channels must be a non-empty subset of 0..19")
        if len(set(active_channels)) != len(active_channels):
            raise ValueError("active_channels must not contain duplicates")
        self.channel_mask = np.zeros(20, dtype=np.float32)
        self.channel_mask[list(active_channels)] = 1.0
        self.hand_mask = np.array(
            [side in self.active_hands for side in HAND_ORDER], dtype=np.float32)
        self.observation_space = gym.spaces.Box(
            -np.inf, np.inf, (OBSERVATION_SIZE,), np.float32)
        self.neutral20 = {}
        self.task_events = []
        self.key_events = None
        self.key_travel = None
        self.previous_action = np.zeros(20, dtype=np.float32)
        self.last_command = {}
        self.edges = []
        self.done = False
        self.home_notes = {
            side: int(home.get("notes", {}).get(side, 60)) for side in HAND_ORDER}
        self.reachable_notes = {
            side: set(range(self.home_notes[side] - 2, self.home_notes[side] + 3))
            for side in HAND_ORDER}

    @classmethod
    def from_config(cls, task_path, package, config_path=None, **overrides):
        package = Path(package).resolve()
        path = _resolve(package, config_path or DEFAULT_CONFIG)
        if path.is_file():
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            document = {}
        values = {
            "scene_config": document.get("scene_config", DEFAULT_SCENE),
            "home_pose": document.get("home_pose", DEFAULT_HOME),
            "pose_file": document.get("pose_file", DEFAULT_POSE),
            "control_dt": document.get("control_dt", 0.02),
            "action_scale": document.get("action_scale", 8.0),
            "ready_curl": document.get("ready_curl", None),
            "active_hands": tuple(document.get("active_hands", HAND_ORDER)),
            "lookahead_sec": tuple(document.get("lookahead_sec", LOOKAHEAD_SEC)),
            "reward_weights": document.get("reward"),
            "active_channels": document.get("active_channels"),
            "observation_lead_sec": document.get("observation_lead_sec", 0.0),
        }
        values.update(overrides)
        return cls(task_path, package, **values)

    @property
    def task_count(self):
        return self.task_set.task_count

    def _make_neutral(self, curl):
        flexion = np.sum(list(self.hand_model.delta.values()), axis=0)
        return np.clip(self.hand_model.ready20 + curl * flexion, 0.0, 255.0)

    def _set_home(self, data):
        commands = self.neutral20
        if self.initial_jitter:
            perturbation = self.np_random.uniform(-1.0, 1.0, 20)
            perturbation *= self.initial_jitter * self.action_mask * self.channel_mask
            commands = self._command(perturbation, scale=1.0)
        for side in HAND_ORDER:
            data.qpos[self.hand_model.arm_qpos[side]] = self.home_q[side]
            data.ctrl[self.hand_model.arm_act[side]] = self.home_q[side]
            targets = self.hand_model.hand_targets(side, commands[side])
            data.qpos[self.hand_model.hand_qpos[side]] = targets
            data.ctrl[self.hand_model.hand_act[side]] = targets

    def _select_task(self, options):
        index = self.task_index
        if options and "task_index" in options:
            index = int(options["task_index"])
        elif self.task_indices:
            index = int(self.np_random.choice(self.task_indices))
        elif isinstance(self.task_set, PianoVamCorpus):
            groups = self.task_set.recording_indices
            if not self._recording_order:
                self._recording_order = self.np_random.permutation(len(groups)).tolist()
            group = groups[self._recording_order.pop()]
            index = int(self.np_random.integers(group.start, group.stop))
        if not 0 <= index < self.task_count:
            raise ValueError("task_index outside the task set")
        self.task_index = index
        self.task = self.task_set.tasks[index]
        if any(event.start_sec < self.task.origin_sec - 1e-9
               for event in self.task.events):
            raise ValueError("carry-in tasks are not supported by PianoDirectEnv")
        self.task_events = self.task.event_views
        self.labeled_events = [event for event in self.task_events if event["finger"] is not None]
        self.end_time = float(self.task.duration_sec)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self._recording_order.clear()
            self.recording_resets.clear()
        self._select_task(options)
        m.mj_resetDataKeyframe(self.model, self.data, self.key_id)
        self.data.time = 0.0
        self.edges = []
        self.episode_edges = []
        self.done = False
        self.reward_model.reset(self.task_events)
        self.key_events = KeyEvents(self.model)
        self.key_travel = KeyTravelMonitor(self.model)
        self.previous_action = np.zeros(20, dtype=np.float32)
        self.neutral20 = {
            side: self._make_neutral(self.ready_curl) for side in HAND_ORDER}
        self._set_home(self.data)
        self.last_command = {
            side: self.neutral20[side].copy() for side in HAND_ORDER}
        m.mj_forward(self.model, self.data)
        contacts, other = self.hand_model.classify(self.data)
        if other:
            self.close()
            raise RuntimeError(f"home pose collides with the scene: {sorted(other)}")
        self.initial_key_contacts = sorted(contacts)
        info = {"task": self.task.id, "task_index": self.task_index,
                "duration_sec": self.end_time, "curl": self.ready_curl,
                "key_contacts": len(contacts)}
        if isinstance(self.task_set, PianoVamCorpus):
            source = self.task_set.task_recordings[self.task_index]
            if not options or "task_index" not in options:
                self.recording_resets[source.recording] += 1
            info.update(recording=source.recording, composer=source.composer,
                        piece=source.piece, source_split=source.task_set.split)
        return self._observation(), info

    def _observation(self):
        time_sec = float(self.data.time) + self.observation_lead_sec
        parts = []
        for side in HAND_ORDER:
            parts.append(self.data.qpos[self.hand_model.hand_qpos[side]] / 3.0)
            parts.append(self.data.qvel[self.hand_dof[side]] / 10.0)
            parts.append(self.data.qpos[self.hand_model.arm_qpos[side]] / math.pi)
            parts.append(self.data.qvel[self.hand_model.arm_dof[side]] / 10.0)
            wrist = self.data.xpos[self.hand_model.wrist_id[side]]
            parts.append(wrist - self.data.site_xpos[self.piano_site])
            parts.append(self.data.xmat[self.hand_model.wrist_id[side]].reshape(9))
        parts.append(self.data.qpos[self.key_qpos] / self.key_limits)
        for ahead in self.lookahead_sec:
            parts.append(target_keys(self.task_events, time_sec + ahead))
        for ahead in self.lookahead_sec:
            for side in HAND_ORDER:
                parts.append(active_fingers(self.labeled_events, side, time_sec + ahead))
        for side in HAND_ORDER:
            parts.append(finger_clock(self.labeled_events, side, time_sec))
        parts.append(self.previous_action)
        parts.append(self.hand_mask)
        remaining = max(0.0, self.end_time - time_sec) / max(self.end_time, 1e-9)
        parts.append(np.array([remaining], dtype=np.float32))
        observation = np.concatenate([np.asarray(part, dtype=np.float32).ravel()
                                      for part in parts])
        if observation.shape != (OBSERVATION_SIZE,):
            raise RuntimeError(f"observation size {observation.shape} != {OBSERVATION_SIZE}")
        if not np.isfinite(observation).all():
            raise RuntimeError("observation contains non-finite values")
        return observation

    def _command(self, action, *, scale=None):
        scale = self.action_scale if scale is None else scale
        command = {}
        for index, side in enumerate(HAND_ORDER):
            values = self.neutral20[side].copy()
            channels = action[index * 10:(index + 1) * 10]
            values[ACTION_CHANNELS] = np.clip(
                values[ACTION_CHANNELS] + scale * channels, 0.0, 255.0)
            command[side] = values
        return command

    def _finger_distances(self):
        time_sec = float(self.data.time)
        target = target_keys(self.task_events, time_sec)
        result = {}
        for index in np.flatnonzero(target):
            note = int(index + 21)
            side = next((event["side"] for event in self.task_events
                         if event["note"] == note and event["on"] <= time_sec < event["off"]),
                        "right")
            site = self.data.site_xpos[self.key_sites[note]]
            best = float("inf")
            for finger in FINGERS:
                gid, vertices = self.fingertips[(side, finger)]
                rotation = self.data.geom_xmat[gid].reshape(3, 3)
                points = self.data.geom_xpos[gid] + vertices @ rotation.T
                best = min(best, float(np.min(np.linalg.norm(points - site, axis=1))))
            result[note] = best
        return result

    def _energy(self):
        total = 0.0
        for side in HAND_ORDER:
            total += float(np.abs(self.data.qfrc_actuator[self.hand_dof[side]])
                           @ np.abs(self.data.qvel[self.hand_dof[side]]))
        return total

    def step(self, action):
        action = np.asarray(action, dtype=np.float32)
        if action.shape != (20,) or not np.isfinite(action).all():
            raise ValueError("action must contain 20 finite values")
        action = np.clip(action, -1.0, 1.0) * self.action_mask * self.channel_mask
        previous_action = self.previous_action.copy()
        command = self._command(action)
        self.last_command = {side: values.copy() for side, values in command.items()}
        self.edges = []
        warning = False
        other_contacts = set()
        onset_contacts = []
        arm_error = 0.0
        for _ in range(self.substeps):
            for side in HAND_ORDER:
                self.data.ctrl[self.hand_model.arm_act[side]] = self.home_q[side]
                self.data.ctrl[self.hand_model.hand_act[side]] = \
                    self.hand_model.hand_targets(side, command[side])
            m.mj_step(self.model, self.data)
            contacts, other = self.hand_model.classify(self.data)
            for time, edge, note in self.key_events.update(self.data):
                self.edges.append((float(time), edge, int(note)))
                if edge == "on":
                    owners = sorted((side, geom) for side, key, geom in contacts if key == note)
                    onset_contacts.append((float(time), int(note), owners))
            self.key_travel.observe(self.data)
            other_contacts.update(other)
            warning = warning or bool(self.data.warning.number.any())
            for side in HAND_ORDER:
                arm_error = max(arm_error, float(np.max(np.abs(
                    self.data.qpos[self.hand_model.arm_qpos[side]] - self.home_q[side]))))
            if warning or other_contacts or arm_error > 0.05:
                break
        self.episode_edges.extend(self.edges)
        out_of_reach = any(
            event.note not in self.reachable_notes[event.hand]
            for event in self.task.events)
        truncated = self.data.time >= self.end_time - 1e-9
        terminated = warning or arm_error > 0.05 or bool(other_contacts)
        violations = self.key_travel.violations()
        reward, components, details = self.reward_model.step(
            time_sec=float(self.data.time),
            key_normalized=self.data.qpos[self.key_qpos] / self.key_limits,
            finger_distances=self._finger_distances(),
            action=action,
            previous_action=previous_action,
            energy=self._energy(),
            other_contacts=len(other_contacts),
            key_excess=float(np.max(self.key_travel.excess)),
            arm_error=arm_error, edges=self.edges)
        if truncated:
            report = evaluate_edges(
                self.task, self.episode_edges, timestep=self.model.opt.timestep,
                key_violations=violations, other_contacts=other_contacts, terminated=terminated)
            if report["success"]:
                components["terminal"] = 10.0
                reward += 10.0
                components["total"] = reward
        self.previous_action = action
        info = {
            "task": self.task.id,
            "task_index": self.task_index,
            "time_sec": float(self.data.time),
            "edges": list(self.edges),
            "onset_contacts": onset_contacts,
            "active_keys": sorted(self.key_events._active),
            "key_violations": violations,
            "other_contacts": sorted(other_contacts),
            "arm_error_rad": arm_error,
            "out_of_reach": bool(out_of_reach),
            "warning": bool(warning),
            "reward_components": components,
            "reward_details": details,
        }
        if terminated and not truncated:
            info["error"] = "safety termination"
        return self._observation(), float(reward), bool(terminated), bool(truncated), info

    def close(self):
        if getattr(self, "hand_model", None) is not None:
            self.hand_model.tmp.cleanup()
            self.hand_model = None

