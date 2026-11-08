"""Build score-aligned controls for calibrated flat-palm transitions."""

import hashlib
import json
from pathlib import Path

import numpy as np


START_DELAY = 0.80
ATTACK_TIME = 0.05
RELEASE_TIME = 0.04
KEY_TIMING_TOLERANCE = 0.025


def smooth(time, start, duration):
    progress = np.clip((time - start) / duration, 0, 1)
    return progress * progress * (3 - 2 * progress)


def transition_targets(time, previous, current, arm, roots, profile, clearance):
    """Overlap releasing, moving the wrist and pressing the next note."""
    release, move_start, move_time, press_start, press_time, lift, opening, lead = profile
    old_ready, old_press, old_hover = previous
    _, new_press, new_hover = current

    released = old_press + smooth(time, 0, release)[:, None] * (old_ready - old_press)
    targets = released + smooth(time, press_start, press_time)[:, None] * (new_press - released)
    travel = smooth(time, move_start, move_time)[:, None]
    wrist = old_press[arm] + travel * (new_press[arm] - old_press[arm])
    lift_up = smooth(time, 0, max(0.02, move_start + move_time * 0.30))
    lift_down = smooth(time, max(0.03, move_start + move_time * 0.65),
                       max(0.025, move_time * 0.50))
    lift_path = old_hover[arm] - old_press[arm]
    lift_path = lift_path + travel * (new_hover[arm] - new_press[arm] - lift_path)
    wrist += lift * (lift_up * (1 - lift_down))[:, None] * lift_path
    if lead and len(time) > 1:
        wrist += lead * np.gradient(wrist, time, axis=0)
    targets[:, arm] = wrist

    if opening:
        release_finger, approach_finger = clearance
        for finger, index in roots.items():
            if finger == release_finger:
                opened = smooth(time, release * 0.35, max(0.022, release * 0.70))
            else:
                opened = smooth(time, 0, 0.026)
            close = press_start - 0.018 if finger == approach_finger else press_start + press_time * 0.65
            opened *= 1 - smooth(time, max(0.02, close), 0.066)
            targets[:, index] = np.maximum(0, targets[:, index] - opening * opened)
    return targets


def hand_targets(plan, notes, time, scale, arm, roots, limits):
    """Expand one calibrated hand trajectory on the physics clock."""
    if plan["pitches"] != [note.note for note in notes]:
        raise ValueError("Motion plan pitches do not match the score")
    poses = np.asarray(plan["poses"], dtype=float)
    if poses.shape != (len(notes), 3, len(limits)) or not np.isfinite(poses).all():
        raise ValueError("Motion plan must provide finite ready, press and hover targets")
    moves = plan["moves"]
    if len(moves) != len(notes) - 1:
        raise ValueError("Motion plan must provide one transition between each pair of notes")

    lead_in, lead_out = (float(plan[name]) for name in ("first_attack_lead", "last_release_lead"))
    if not (0 <= lead_in <= START_DELAY and 0 <= lead_out <= START_DELAY):
        raise ValueError("Motion plan attack and release leads are out of range")
    attack = START_DELAY + notes[0].start * scale - lead_in
    ready, press, _ = poses[0]
    track = ready + smooth(time, attack, ATTACK_TIME)[:, None] * (press - ready)
    begins = [attack]
    last_start = attack
    for index, move in enumerate(moves):
        old, new = notes[index:index + 2]
        profile = np.asarray(move["profile"], dtype=float)
        edges = np.asarray(move["edges"], dtype=float)
        clearance = move.get("clearance", ["index", "little"])
        if (profile.shape != (8,) or not np.isfinite(profile).all() or np.any(profile < 0)
                or min(profile[[0, 2, 4]]) == 0 or edges.shape != (2,)
                or not np.isfinite(edges).all() or not 0 < edges[0] < edges[1]
                or len(clearance) != 2 or any(finger not in roots for finger in clearance)):
            raise ValueError(f"Invalid motion plan transition {index + 1}")
        expected_gap = (new.start - old.end) * scale
        balance = (edges[1] - edges[0] - expected_gap) / 2
        start = START_DELAY + old.end * scale - edges[0] - balance
        if not last_start < start < START_DELAY + new.start * scale:
            raise ValueError(f"Motion plan transition {index + 1} is out of order")
        active = time >= start
        track[active] = transition_targets(time[active] - start, poses[index], poses[index + 1],
                                            arm, roots, profile, clearance)
        begins.append(start + profile[3])
        last_start = start

    off = START_DELAY + notes[-1].end * scale - lead_out
    if off <= last_start:
        raise ValueError("Motion plan ends before its last attack")
    active = time >= off
    ready, press, _ = poses[-1]
    track[active] = press + smooth(time[active], off, RELEASE_TIME)[:, None] * (ready - press)
    if not np.isfinite(track).all():
        raise ValueError("Motion plan generated a nonfinite control")
    windows = [
        (begin, START_DELAY + note.end * scale + 0.06, note.note,
         START_DELAY + note.start * scale, START_DELAY + note.end * scale)
        for note, begin in zip(notes, begins)
    ]
    if any(b[0] < a[0] for a, b in zip(windows, windows[1:])):
        raise ValueError("Motion plan strike windows are out of order")
    # The original hand presets can include thumb targets outside the actuator range.
    # Apply the same limits as the position actuators to the expanded commands.
    return np.clip(track, limits[:, 0], limits[:, 1]), np.clip(poses[0, 0], *limits.T), windows


def load_motion_plan(path, signature):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("signature") != signature:
        raise ValueError("Motion plan does not match the score, scene, model, poses or fingering")
    if set(plan["hands"]) != {"left", "right"}:
        raise ValueError("Motion plan requires both hands")
    return plan["hands"]


def motion_signature(score, paths, scale, timestep, key_press_deg=None, key_release_deg=None):
    signature = {name: hashlib.sha256(Path(path).read_text(encoding="utf-8").encode()).hexdigest()
                 for name, path in paths.items()}
    signature.update(score=hashlib.sha256(Path(score).read_bytes()).hexdigest(), scale=scale,
                     timestep=timestep, key_press_deg=key_press_deg, key_release_deg=key_release_deg)
    return signature
