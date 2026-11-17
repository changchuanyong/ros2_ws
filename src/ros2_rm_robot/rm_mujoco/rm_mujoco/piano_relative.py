"""Reuse calibrated finger commands at the same hand-relative key geometry."""

from dataclasses import dataclass
import math

import numpy as np

from .performance import FINGERS
from .pianovam_tasks import HAND_ORDER


def _finger_channels(hand, finger):
    root = 10 * HAND_ORDER.index(hand) + FINGERS.index(finger)
    return root, root + 5


@dataclass(frozen=True)
class RelativeKeyTarget:
    hand: str
    lateral_m: float
    black: bool
    duration_sec: float
    channels: frozenset[int]

    def __post_init__(self):
        if (self.hand not in HAND_ORDER or not math.isfinite(self.lateral_m)
                or not math.isfinite(self.duration_sec) or self.duration_sec <= 0):
            raise ValueError("invalid relative key hand, geometry or duration")

    @property
    def candidate_fingers(self):
        return tuple(finger for finger in FINGERS
                     if self.channels.intersection(_finger_channels(self.hand, finger)))


@dataclass(frozen=True)
class RelativeStrike:
    hand: str
    finger: str
    lateral_m: float
    black: bool
    duration_sec: float
    phases: tuple[tuple[int, float, float], ...]  # (control ticks, normalized ROOT, normalized TIP)

    def __post_init__(self):
        if self.hand not in HAND_ORDER or self.finger not in FINGERS:
            raise ValueError("invalid strike hand or finger")
        if not math.isfinite(self.lateral_m) or not math.isfinite(self.duration_sec) or self.duration_sec <= 0:
            raise ValueError("strike geometry and duration must be finite and duration positive")
        if not self.phases or any(
                isinstance(ticks, bool) or not isinstance(ticks, (int, np.integer)) or ticks <= 0
                or not -1.0 <= root <= 1.0 or not -1.0 <= tip <= 1.0
                for ticks, root, tip in self.phases):
            raise ValueError("strike phases must contain positive ticks and bounded ROOT/TIP commands")


def strike_commands(target, profiles, *, max_lateral_error_m=0.003):
    """Select by geometry and duration, returning actions for the normal env.step path."""
    if not math.isfinite(max_lateral_error_m) or max_lateral_error_m < 0:
        raise ValueError("max_lateral_error_m must be finite and non-negative")
    candidates = []
    for profile in profiles:
        if profile.hand != target.hand or profile.black != target.black:
            continue
        position_error = abs(profile.lateral_m - target.lateral_m)
        if position_error > max_lateral_error_m or profile.finger not in target.candidate_fingers:
            continue
        root, tip = _finger_channels(profile.hand, profile.finger)
        if any((r and root not in target.channels) or (t and tip not in target.channels)
               for _, r, t in profile.phases):
            continue
        candidates.append((abs(profile.duration_sec - target.duration_sec), position_error, profile))
    if not candidates:
        raise ValueError("no calibrated strike matches the relative key and active fingers")
    _, _, profile = min(candidates, key=lambda item: item[:2])
    root, tip = _finger_channels(profile.hand, profile.finger)
    commands = []
    for ticks, r, t in profile.phases:
        action = np.zeros(20, dtype=np.float32)
        action[root], action[tip] = r, t
        commands.append((int(ticks), action))
    return commands
