"""Physical reward for reference-free L20 piano control.

The reward is computed from MuJoCo key angles and fingertip distances.  It is
deliberately independent of the old residual PPO and of any reference plan.
"""

from dataclasses import dataclass
import math

import numpy as np

from .piano_direct_eval import TIMING_TOLERANCE_SEC, TIME_EPSILON

KEY_PRESS_FRACTION = 0.55
FINGER_SCALE_M = 0.02
SAFETY_KEY_EXCESS_M = 0.01
SAFETY_ARM_ERROR_RAD = 0.05


def _target_keys(events, time_sec):
    target = np.zeros(88, dtype=np.float32)
    for event in events:
        if event["on"] <= time_sec < event["off"]:
            target[event["note"] - 21] = 1.0
    return target


def _timing_reward(error):
    """Give more credit near the target within the accepted timing window."""
    error = abs(float(error))
    relative = error / TIMING_TOLERANCE_SEC
    if error <= TIMING_TOLERANCE_SEC + TIME_EPSILON:
        return 1.0 - 0.75 * relative
    return -min(4.0, 1.0 + (relative - 1.0) ** 2)


@dataclass(frozen=True)
class RewardWeights:
    key: float = 1.0
    finger: float = 0.2
    timing: float = 0.5
    energy: float = 0.005
    action: float = 0.01
    safety: float = 2.0

    @classmethod
    def from_mapping(cls, values=None):
        values = values or {}
        allowed = {"key", "finger", "timing", "energy", "action", "safety"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unknown reward weights: {sorted(unknown)}")
        result = {}
        for name in allowed:
            value = float(values.get(name, getattr(cls, name)))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"reward weight {name} must be finite and non-negative")
            result[name] = value
        return cls(**result)


class DirectReward:
    """Per-control-step reward with separately reported physical components."""

    def __init__(self, weights=None):
        self.weights = (weights if isinstance(weights, RewardWeights)
                        else RewardWeights.from_mapping(weights))
        self.events = []
        self.press_count = 0
        self.release_count = 0
        self.missing_count = 0
        self.late_release_count = 0

    def reset(self, events):
        self.events = [{
            "id": event["id"], "note": int(event["note"]),
            "on": float(event["on"]), "off": float(event["off"]),
            "pressed": False, "released": False, "on_time": False,
            "missing_penalized": False, "late_penalized": False,
            "press_error": None, "release_error": None,
        } for event in events]
        self.press_count = 0
        self.release_count = 0
        self.missing_count = 0
        self.late_release_count = 0
        self.last_sounding = np.zeros(88, dtype=bool)
        self.active_events = {}

    def _timing(self, time_sec, edges):
        timing = 0.0
        for edge_time, edge, note in edges:
            self.last_sounding[note - 21] = edge == "on"
            if edge == "on":
                eligible = (event for event in self.events
                            if event["note"] == note and not event["pressed"]
                            and event["on"] - TIMING_TOLERANCE_SEC - TIME_EPSILON <= edge_time
                            < event["off"])
                event = min(eligible, key=lambda item: abs(item["on"] - edge_time),
                            default=None)
                if event is None:
                    timing -= 1.0
                    continue
                error = edge_time - event["on"]
                event["pressed"] = True
                event["press_error"] = error
                event["on_time"] = abs(error) <= TIMING_TOLERANCE_SEC + TIME_EPSILON
                self.active_events[note] = event
                self.press_count += 1
                timing += _timing_reward(error)
            elif note in self.active_events:
                event = self.active_events.pop(note)
                error = edge_time - event["off"]
                event["released"] = True
                event["release_error"] = error
                self.release_count += 1
                timing += _timing_reward(error)
                timing += 0.5 * _timing_reward(error - event["press_error"])
        for event in self.events:
            if (not event["pressed"] and not event["missing_penalized"]
                    and time_sec > event["on"] + TIMING_TOLERANCE_SEC + TIME_EPSILON):
                event["missing_penalized"] = True
                self.missing_count += 1
                timing -= 1.0
            if (event["pressed"] and not event["released"] and not event["late_penalized"]
                    and time_sec > event["off"] + TIMING_TOLERANCE_SEC + TIME_EPSILON):
                event["late_penalized"] = True
                self.late_release_count += 1
                timing -= 1.0
        return timing

    def strict_timing(self, tolerance_sec=TIMING_TOLERANCE_SEC):
        return bool(self.events) and all(
            event["pressed"] and event["released"]
            and event["press_error"] is not None
            and event["release_error"] is not None
            and abs(event["press_error"]) <= tolerance_sec
            and abs(event["release_error"]) <= tolerance_sec
            for event in self.events)

    def step(self, *, time_sec, key_normalized, finger_distances=None,
             action=None, previous_action=None, energy=0.0,
             other_contacts=0, key_excess=0.0, arm_error=0.0, edges=None):
        time_sec = float(time_sec)
        key_normalized = np.asarray(key_normalized, dtype=float)
        if key_normalized.shape != (88,) or not np.isfinite(key_normalized).all():
            raise ValueError("key_normalized must contain 88 finite values")
        action = (np.zeros(20, dtype=float) if action is None
                  else np.asarray(action, dtype=float))
        previous_action = (np.zeros(20, dtype=float) if previous_action is None
                           else np.asarray(previous_action, dtype=float))
        if action.shape != (20,) or previous_action.shape != (20,):
            raise ValueError("action and previous_action must contain 20 values")
        if not np.isfinite(action).all() or not np.isfinite(previous_action).all():
            raise ValueError("action and previous_action must be finite")
        if edges is None:
            sounding = key_normalized >= KEY_PRESS_FRACTION
            edges = [(time_sec, "on" if sounding[index] else "off", int(index + 21))
                     for index in np.flatnonzero(sounding != self.last_sounding)]
        timing = self._timing(time_sec, edges)
        sounding = self.last_sounding
        target = _target_keys(
            (event for event in self.events
             if event["on_time"] or (not event["pressed"] and not event["missing_penalized"])),
            time_sec + TIME_EPSILON)
        target_count = float(target.sum())
        wrong_count = float(np.count_nonzero(sounding & (target == 0)))
        missing_count = float(np.count_nonzero(~sounding & (target == 1)))
        correct_count = float(np.count_nonzero(sounding & (target == 1)))
        correct_fraction = correct_count / target_count if target_count else 0.0
        missing_fraction = missing_count / target_count if target_count else 0.0
        wrong_ratio = wrong_count / max(target_count, wrong_count, 1.0)
        key = correct_fraction - missing_fraction - 2.0 * wrong_ratio

        finger = 0.0
        distances = finger_distances or {}
        active_notes = np.flatnonzero(sounding & (target == 1))
        if len(active_notes):
            values = [math.exp(-float(distances.get(int(note + 21), 0.2))
                               / FINGER_SCALE_M) for note in active_notes]
            finger = float(np.mean(values))

        action_penalty = float(np.mean(action ** 2))
        action_penalty += float(np.mean((action - previous_action) ** 2))
        safety_penalty = (max(0, int(other_contacts))
                          + min(1.0, max(0.0, float(key_excess)) / SAFETY_KEY_EXCESS_M)
                          + max(0.0, float(arm_error)) / SAFETY_ARM_ERROR_RAD)
        weights = self.weights
        components = {
            "key": weights.key * key,
            "finger": weights.finger * finger,
            "timing": weights.timing * timing,
            "energy": -weights.energy * max(0.0, float(energy)),
            "action": -weights.action * action_penalty,
            "safety": -weights.safety * safety_penalty,
        }
        total = float(sum(components.values()))
        components["total"] = total
        details = {
            "correct_keys": correct_count,
            "wrong_keys": wrong_count,
            "missing_keys": missing_count,
            "press_count": self.press_count,
            "release_count": self.release_count,
            "missing_events": self.missing_count,
            "late_release_events": self.late_release_count,
            "sounding": sorted(int(note + 21) for note in np.flatnonzero(sounding)),
        }
        return total, components, details


