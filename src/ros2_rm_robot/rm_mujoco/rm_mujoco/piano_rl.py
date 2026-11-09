"""Simulation-only, score-conditioned residual control for one or two L20 hands.

Reference arm and hand tracks come from a validated piano_performance/1 plan.
Actions adjust the five ROOT and five TIP command channels, in L20 units.
The original replay runner remains the authority for physical acceptance.
"""

import importlib.util
from pathlib import Path

import gymnasium as gym
import mujoco as m
import numpy as np

from .keyboard import KEY_NOTES, key_site_name
from .l20_joint_mapping import HAND_JOINT_SUFFIXES, command_positions
from .performance import FINGERS, load_plan


ACTION_CHANNELS = np.array([0, 1, 2, 3, 4, 15, 16, 17, 18, 19])
LOOKAHEAD_SEC = (0.0, 0.05, 0.10, 0.20, 0.40)
FINGER_BOUNDS_M = 0.01
FINGER_MARGIN_M = 0.1
ENERGY_WEIGHT = 0.005
REWARD_VERSION = "piano_residual/5"
INTERFACE_VERSION = "piano_shared_hands/3"
HAND_ORDER = ("right", "left")


def episode_steps(plan, control_dt):
    tempo = float(plan["metadata"].get("tempo_scale", 1.0))
    tail = [event["end_sec"] for hand in plan["hands"].values()
            for event in hand["events"]]
    tail += [state["time_sec"] for hand in plan["hands"].values()
             for state in hand["hand_states"]]
    tail += [point["time_sec"] for hand in plan["hands"].values()
             for point in hand["arm_waypoints"]]
    return int(np.ceil((max(tail) * tempo + 0.6) / control_dt))


def finger_clock(events, side, time_sec):
    """Give each finger its next pitch, onset/off countdown and held flag."""
    result = np.zeros((5, 4), dtype=np.float32)
    for index, finger in enumerate(FINGERS):
        upcoming = [event for event in events if event["side"] == side
                    and event["finger"] == finger and event["off"] > time_sec
                    and event["on"] <= time_sec + 0.4]
        if upcoming:
            event = min(upcoming, key=lambda item: item["on"])
            result[index] = [(event["note"] - 64) / 44,
                             np.clip((event["on"] - time_sec) / 0.4, -1, 1),
                             np.clip((event["off"] - time_sec) / 0.4, -1, 1),
                             float(event["on"] <= time_sec)]
    return result.ravel()


def active_fingers(events, side, time_sec):
    """RoboPianist-style fingering labels for one piano-roll lookahead."""
    result = np.zeros(5, dtype=np.float32)
    for event in events:
        if (event["side"] == side and event["on"] <= time_sec < event["off"]):
            finger = event.get("prior_finger") or event["finger"]
            result[FINGERS.index(finger)] = 1.0
    return result


def f1_score(counts):
    """Aggregate frame-level key precision, recall and F1."""
    true_positive, false_positive, false_negative = (int(value) for value in counts)
    precision = (true_positive / (true_positive + false_positive)
                 if true_positive + false_positive else 1.0)
    recall = (true_positive / (true_positive + false_negative)
              if true_positive + false_negative else 1.0)
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall else 0.0)
    return {"precision": float(precision), "recall": float(recall), "f1": float(f1),
            "true_positive": true_positive, "false_positive": false_positive,
            "false_negative": false_negative}


def tolerance(value, bounds, margin):
    distance = max(float(value) - bounds, 0.0)
    if distance == 0.0:
        return 1.0
    return float(np.exp(np.log(0.1) * (distance / margin) ** 2))


def load_replay(package):
    """Load the existing source-tree evaluator without copying its gates."""
    path = Path(package) / "scripts/run_performance.py"
    spec = importlib.util.spec_from_file_location("_piano_rl_replay", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def target_keys(events, time_sec):
    target = np.zeros(88, dtype=np.float32)
    for event in events:
        if event["on"] <= time_sec < event["off"]:
            target[event["note"] - 21] = 1.0
    return target


def key_reward(normalized, target, threshold_wrong=False):
    pressure = np.clip(normalized / 0.55, 0.0, 1.0)
    missing = np.sum((1.0 - pressure) * target)
    wrong = (float(np.any((normalized >= 0.55) & (target == 0))) if threshold_wrong
             else np.sum(pressure * (1.0 - target)))
    excess = np.sum(np.maximum(normalized - 1.0, 0.0))
    margin = np.sum((np.maximum(normalized - 0.85, 0.0) / 0.15) ** 2 * target)
    return 1.0 - 2.0 * missing - 3.0 * wrong - 50.0 * excess - 0.25 * margin


class PianoResidualEnv(gym.Env):
    """Bounded hand corrections over an unchanged reference wrist trajectory."""

    metadata = {"render_modes": []}

    def __init__(self, plan_path, package, *, control_dt=0.02, residual=6.0,
                 robopianist_reward=False, command_bias=0.0, threshold_wrong=False):
        super().__init__()
        if not np.isfinite(control_dt) or control_dt <= 0:
            raise ValueError("control_dt must be finite and positive")
        if not np.isfinite(residual) or not 0 < residual <= 20:
            raise ValueError("residual must be in (0, 20] L20 command units")
        self.package = Path(package).resolve()
        self.plan_path = Path(plan_path).resolve()
        self.plan = load_plan(self.plan_path)
        self.sides = tuple(side for side in HAND_ORDER if side in self.plan["hands"])
        if not np.isfinite(command_bias) or not 0 <= command_bias <= 2:
            raise ValueError("command_bias must be in [0, 2] L20 units")
        self.command_bias = float(command_bias)
        self.threshold_wrong = bool(threshold_wrong)
        self.replay = load_replay(self.package)
        self.control_dt = float(control_dt)
        self.residual = float(residual)
        self.robopianist_reward = bool(robopianist_reward)
        self.runner = None
        self.action_space = gym.spaces.Box(-1.0, 1.0, (20,), np.float32)
        self.action_mask = np.repeat([side in self.sides for side in HAND_ORDER], 10)
        hand_size = 42 + 14 + 20 + 3 + 88 * len(LOOKAHEAD_SEC) + 5 * len(LOOKAHEAD_SEC) + 20 + 21
        size = hand_size * 2 + 88 + 56 + 20 + 2 + 1
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, (size,), np.float32)
        self.total_control_steps = 0
        self.completed_episodes = 0
        self.seen_events = set()
        self.nominal_qpos = None

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.close()
        tempo = float(self.plan["metadata"].get("tempo_scale", 1.0))
        tolerance = float(self.plan["metadata"].get("timing_tolerance_sec", 0.03))
        self.runner = self.replay.PlanRunner(
            self.plan, self.package, self.package / "config/piano_scene.yaml",
            self.package / "models/rm_75_6fb_v_dual_l20.xml", tempo, tolerance,
            None, None)
        r = self.runner
        ratio = self.control_dt / r.model.opt.timestep
        if abs(ratio - round(ratio)) > 1e-8 or ratio < 1:
            self.close()
            raise ValueError("control_dt must be a positive multiple of the physics timestep")
        self.substeps = round(ratio)
        self.hand_dofs = {side: np.array([
            int(r.model.joint(f"{side}_{suffix}").dofadr[0])
            for suffix in HAND_JOINT_SUFFIXES]) for side in self.sides}
        self.arm_dofs = {side: np.array([
            int(r.model.joint(f"{side}_joint{i}").dofadr[0]) for i in range(1, 8)])
            for side in self.sides}
        self.hand_dof = np.concatenate(list(self.hand_dofs.values()))
        self.forearm_sites = {side: int(r.model.site(f"{side}_l20_mount").id)
                              for side in self.sides}
        self.piano_body = int(r.model.body("piano_environment").id)
        self.bias = self.np_random.uniform(
            -self.command_bias, self.command_bias, self.action_space.shape) * self.action_mask
        joints = [r.model.joint(f"piano_key_{note:03d}_hinge") for note in KEY_NOTES]
        self.key_qpos = np.array([int(joint.qposadr[0]) for joint in joints])
        self.key_limits = np.array([float(joint.range[1]) for joint in joints])
        self.key_sites = np.array([
            r.model.site(key_site_name(note)).id for note in KEY_NOTES])
        self.fingertip = self._build_fingertips() if self.robopianist_reward else {}
        tail = [event["off"] for event in r.expected]
        tail += [state["time_sec"] * tempo for side in self.sides
                 for state in self.plan["hands"][side]["hand_states"]]
        tail += [point["time_sec"] * tempo for side in self.sides
                 for point in self.plan["hands"][side]["arm_waypoints"]]
        self.end_time = max(tail) + 0.6
        self.previous_action = np.zeros(self.action_space.shape, dtype=np.float32)
        self.episode_return = 0.0
        self.reward_components = dict.fromkeys(
            ("key", "finger", "energy", "action", "event", "timing", "safety", "terminal"), 0.0)
        self.event_potential = 0.0
        self.timing_potential = 0.0
        self.safety_potential = 0.0
        self.fingertip_distance_total = 0.0
        self.fingertip_distance_samples = 0
        self.energy_total = 0.0
        self.energy_samples = 0
        self.key_confusion = np.zeros(3, dtype=np.int64)
        self.done = False
        self.action_trace = []
        if r.dual:
            r._check_contacts(r.data.time)
        return self._observation(), {}

    def _build_fingertips(self):
        r = self.runner
        result = {}
        for side, finger in ((side, finger) for side in self.sides for finger in FINGERS):
            mesh = r.model.mesh(f"l20_{finger}_link{5 if finger == 'thumb' else 4}")
            gid = next(
                i for i in range(r.model.ngeom)
                if r.model.geom_type[i] == m.mjtGeom.mjGEOM_MESH
                and r.model.geom_dataid[i] == mesh.id
                and r.geom_names[i].startswith(f"{side}_"))
            vertices = r.model.mesh_vert[
                mesh.vertadr[0]:mesh.vertadr[0] + mesh.vertnum[0]]
            rotation = r.data.geom_xmat[gid].reshape(3, 3)
            local = vertices[np.argmin((vertices @ rotation.T)[:, 2])].copy()
            result[side, finger] = (gid, local)
        return result

    def _finger_reward(self):
        r = self.runner
        active = [event for event in r.expected
                  if event["on"] <= r.data.time < event["off"]]
        if not active:
            return 0.0
        values = []
        for event in active:
            finger = event["prior_finger"] or event["finger"]
            gid, local = self.fingertip[event["side"], finger]
            tip = (r.data.geom_xpos[gid]
                   + r.data.geom_xmat[gid].reshape(3, 3) @ local)
            key = r.data.site_xpos[self.key_sites[event["note"] - 21]]
            distance = float(np.linalg.norm(tip - key))
            self.fingertip_distance_total += distance
            self.fingertip_distance_samples += 1
            values.append(tolerance(distance, FINGER_BOUNDS_M, FINGER_MARGIN_M))
        return float(np.mean(values))

    def _observation(self):
        r = self.runner
        time_sec = r.data.time
        features = []
        hand_size = 42 + 14 + 20 + 3 + 88 * len(LOOKAHEAD_SEC) + 5 * len(LOOKAHEAD_SEC) + 20 + 21
        for side in HAND_ORDER:
            if side not in self.sides:
                features.append(np.zeros(hand_size))
                continue
            reference = r.hand_tracks[side].at(time_sec)
            events = [event for event in r.expected if event["side"] == side]
            forearm = (r.data.site_xpos[self.forearm_sites[side]]
                       - r.data.xpos[self.piano_body])
            features.extend([
                r.data.qpos[r.hand_qpos[side]] / 3.0,
                r.data.qvel[self.hand_dofs[side]] / 10.0,
                r.data.qpos[r.arm_qpos[side]] / np.pi,
                r.data.qvel[self.arm_dofs[side]] / 10.0,
                reference / 255.0,
                forearm,
                *(target_keys(events, time_sec + ahead) for ahead in LOOKAHEAD_SEC),
                *(active_fingers(events, side, time_sec + ahead) for ahead in LOOKAHEAD_SEC),
                finger_clock(r.expected, side, time_sec),
                (np.asarray(command_positions(reference)) - r.data.qpos[r.hand_qpos[side]]) / 0.1,
            ])
        return np.concatenate([
            *features,
            r.data.qpos[self.key_qpos] / self.key_limits,
            self.reference_error() / 0.02,
            self.previous_action,
            [float(side in self.sides) for side in HAND_ORDER],
            [max(0.0, self.end_time - time_sec) / self.end_time],
        ]).astype(np.float32)

    def set_nominal_trace(self, positions):
        """Use a validated unperturbed replay as the causal tracking reference."""
        positions = np.asarray(positions, dtype=float)
        if (positions.ndim != 2 or self.runner is None
                or positions.shape[1] != self.runner.model.nq
                or len(positions) < episode_steps(self.plan, self.control_dt)
                or not np.isfinite(positions).all()):
            raise ValueError("nominal trace must cover the entire episode with finite qpos")
        self.nominal_qpos = positions

    def reference_error(self):
        if self.nominal_qpos is None:
            return np.zeros(56)
        index = min(len(self.action_trace), len(self.nominal_qpos) - 1)
        reference = self.nominal_qpos[index]
        r = self.runner
        return np.concatenate([
            np.concatenate([r.data.qpos[r.hand_qpos[side]] - reference[r.hand_qpos[side]],
                            r.data.qpos[r.arm_qpos[side]] - reference[r.arm_qpos[side]]])
            if side in self.sides else np.zeros(28) for side in HAND_ORDER])

    def _event_potential(self):
        """Credit released notes using the replay's original timing/duration gates."""
        r = self.runner
        matched, missing, unexpected, _, _ = r._match_events(r._actual_spans())
        deadline = r.data.time - r.timing_tolerance

        def due(event):
            return event.get("expected_off", event.get("off")) <= deadline

        return 5.0 * (
            sum(due(event) for event in matched)
            - 2 * sum(due(event) for event in missing)
            - 2 * sum(event["kind"] == "extra" or due(event)
                      for event in unexpected))

    def _timing_potential(self):
        """Reward timing margin continuously without changing acceptance limits."""
        r = self.runner
        matched, _, _, _, _ = r._match_events(r._actual_spans())
        due = [event for event in matched
               if event["expected_off"] <= r.data.time - r.timing_tolerance]
        return -2.0 * sum(
            min(4.0, (event["onset_error"] / r.timing_tolerance) ** 2)
            + min(4.0, (event["release_error"] / r.timing_tolerance) ** 2)
            + min(4.0, (event["duration_error"] / event["duration_tolerance_sec"]) ** 2)
            for event in due)

    def step(self, action):
        if self.runner is None or self.done:
            raise RuntimeError("reset is required before stepping an episode")
        action = np.asarray(action, dtype=np.float32)
        if action.shape != self.action_space.shape or not np.isfinite(action).all():
            raise ValueError(f"action must contain {self.action_space.shape[0]} finite values")
        action = np.clip(action, -1.0, 1.0) * self.action_mask
        policy_action = action.copy()
        error = float(np.max(np.abs(self.reference_error())))
        gate = (1.0 if self.nominal_qpos is None else
                (0.0 if error <= 1e-9 else min(1.0, error / 0.002)))
        action *= gate
        r = self.runner
        key_total = 0.0
        finger_total = 0.0
        energy_total = 0.0
        self.action_trace.append({"time_sec": float(r.data.time), "action": action.tolist(),
                                  "policy_action": policy_action.tolist(), "tracking_gate": gate})
        for _ in range(self.substeps):
            for side in self.sides:
                index = HAND_ORDER.index(side)
                channels = slice(index * 10, (index + 1) * 10)
                r.data.ctrl[r.arm_act[side]] = r.arm_tracks[side].at(r.data.time)
                command = r.hand_tracks[side].at(r.data.time).copy()
                command[ACTION_CHANNELS] += self.residual * action[channels] + self.bias[channels]
                command = np.clip(command, 0.0, 255.0)
                r.data.ctrl[r.hand_act[side]] = command_positions(command.tolist())
            before = r.data.time
            m.mj_step(r.model, r.data)
            if r.data.time <= before or r.data.warning.number.any():
                raise RuntimeError("unstable MuJoCo trajectory")
            step_edges = r.key_events.update(r.data)
            for time_sec, edge, note in step_edges:
                r.edges.append((float(time_sec), edge, int(note)))
                if edge == "on":
                    r.active_key_notes.add(int(note))
                    r.active_onsets[note] = time_sec
                else:
                    r.active_key_notes.discard(int(note))
                    r.active_onsets.pop(note, None)
                    r.recent_key_contacts.pop(note, None)
            r._check_contacts(r.data.time)
            if r.dual:
                current = {}
                for contact in r._active_contacts:
                    current.setdefault(contact[1], []).append(contact)
                for note, contacts in current.items():
                    r.recent_key_contacts[note] = r.data.time, sorted(contacts)
                for time_sec, edge, note in step_edges:
                    last = r.recent_key_contacts.get(note)
                    if edge == "on" and last and time_sec - last[0] <= r.contact_tolerance:
                        r.onset_contacts[time_sec, note] = last
            angles = r.key_travel.observe(r.data)
            normalized = angles / self.key_limits
            target = target_keys(r.expected, r.data.time)
            sounding = normalized >= 0.55
            self.key_confusion += [np.count_nonzero(sounding & (target == 1)),
                                   np.count_nonzero(sounding & (target == 0)),
                                   np.count_nonzero(~sounding & (target == 1))]
            self.seen_events.update((event["side"], event["id"])
                                    for event in r.expected if event["on"] <= r.data.time)
            key_total += key_reward(normalized, target, self.threshold_wrong)
            if self.robopianist_reward:
                finger_total += self._finger_reward()
                energy = float(np.abs(r.data.qfrc_actuator[self.hand_dof])
                               @ np.abs(r.data.qvel[self.hand_dof]))
                energy_total += energy
                self.energy_total += energy
                self.energy_samples += 1
            if r.data.time >= self.end_time:
                break
        self.reward_components["key"] += key_total / self.substeps
        self.reward_components["finger"] += finger_total / self.substeps
        self.reward_components["energy"] -= ENERGY_WEIGHT * energy_total / self.substeps
        reward = ((key_total + finger_total - ENERGY_WEIGHT * energy_total)
                  / self.substeps)
        action_penalty = -0.01 * float(np.mean(action ** 2))
        action_penalty -= 0.01 * float(np.mean((action - self.previous_action) ** 2))
        self.reward_components["action"] += action_penalty
        reward += action_penalty
        potential = self._event_potential()
        event_reward = potential - self.event_potential
        self.reward_components["event"] += event_reward
        reward += event_reward
        self.event_potential = potential
        timing = self._timing_potential()
        timing_reward = timing - self.timing_potential
        self.reward_components["timing"] += timing_reward
        reward += timing_reward
        self.timing_potential = timing
        safety = -50.0 * (np.count_nonzero(r.key_travel.excess_steps)
                          + bool(r.wrong_finger_contacts) + len(r.unexpected_contacts))
        safety_reward = safety - self.safety_potential
        self.reward_components["safety"] += float(safety_reward)
        reward += safety_reward
        self.safety_potential = safety
        self.previous_action = action.copy()
        self.total_control_steps += 1
        self.done = r.data.time >= self.end_time
        info = {}
        if self.done:
            self.completed_episodes += 1
            report = r._report()
            terminal = 10.0 if report["passed"] else -float(
                2 * len(report["missing"]) + 2 * len(report["unexpected"])
                + len(report["angle_violations"]) + len(report["active_keys_at_end"]))
            self.reward_components["terminal"] += terminal
            reward += terminal
            info["report"] = report
            info["reward_components"] = self.reward_components.copy()
        self.episode_return += float(reward)
        if self.done:
            info["episode"] = {"r": self.episode_return,
                               "l": len(self.action_trace)}
        return self._observation(), float(reward), self.done, False, info

    def close(self):
        if self.runner is not None:
            self.runner.tmp.cleanup()
            self.runner = None


class PianoTaskCycle(gym.Env):
    """Visit every task, then balance either episode counts or control steps."""

    metadata = {"render_modes": []}

    def __init__(self, tasks, balance="episode"):
        super().__init__()
        if not tasks:
            raise ValueError("at least one training task is required")
        if balance not in {"episode", "step"}:
            raise ValueError("balance must be 'episode' or 'step'")
        self.tasks = tasks
        self.balance = balance
        self.episode_lengths = np.array([
            episode_steps(task.plan, task.control_dt) for task in tasks])
        self.selected_episodes = np.zeros(len(tasks), dtype=np.int64)
        self.action_space = tasks[0].action_space
        self.observation_space = tasks[0].observation_space
        self.order = np.arange(len(tasks))
        self.cursor = 0
        self.active = None

    def _next_cycle(self):
        if self.balance == "step":
            repeats = np.ceil(self.episode_lengths.max() / self.episode_lengths).astype(int)
            self.order = np.repeat(np.arange(len(self.tasks)), repeats)
        else:
            self.order = np.arange(len(self.tasks))
        self.np_random.shuffle(self.order)
        self.cursor = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self.order = np.arange(len(self.tasks))
            self.cursor = 0
            self.selected_episodes.fill(0)
        if self.cursor == len(self.order):
            self._next_cycle()
        index = int(self.order[self.cursor])
        self.cursor += 1
        self.selected_episodes[index] += 1
        self.active = self.tasks[index]
        obs, info = self.active.reset(seed=int(self.np_random.integers(2**31 - 1)))
        return obs, {**info, "task_index": index}

    def step(self, action):
        if self.active is None:
            raise RuntimeError("reset is required before stepping")
        return self.active.step(action)

    def close(self):
        for task in self.tasks:
            task.close()
