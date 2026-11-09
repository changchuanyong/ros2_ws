#!/usr/bin/env python3
"""Replay the calibrated right-hand tail through the production scheduler.

Reads `config/right_tail_v29.yaml` -- the six two_tigers events 33-40 solved in
`.validation/dual_two_tigers_1x_20261108/final_tail_v29` -- and replays them with
`FingeringPlanner._schedule_candidate`, without monkey patches.  Writes a
`piano_performance/1` plan when every event is accepted.

Usage:
    python3 verify_right_tail.py --output right_tail.performance.yaml
"""

import argparse
import math
from pathlib import Path
import sys
import time

import numpy as np
import yaml

try:
    from ament_index_python.packages import get_package_share_directory
except ImportError:  # source-tree use before sourcing an install
    get_package_share_directory = None

from rm_mujoco.fingering import Candidate, FingeringPlanner, PianoHandModel
from rm_mujoco.performance import group_events, validate_plan, write_plan

FORMAT = "piano_right_tail/1"
# 索引指的抬指通道：v29 标定和 probe 探针都改这一路。
LIFT_CHANNEL = 1
TAIL_FINGER = "index"


def _default_package():
    if get_package_share_directory is not None:
        try:
            return Path(get_package_share_directory("rm_mujoco"))
        except Exception:
            pass
    return Path(__file__).resolve().parents[1]


def _seconds(value, name):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return seconds


def _pose(values, name, count):
    array = np.asarray(values, dtype=float)
    if array.shape != (count,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain {count} finite values")
    return array


def load_tail(path):
    """Parse and validate a `piano_right_tail/1` calibration."""
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError(f"tail calibration must declare format {FORMAT}")
    finger = document.get("finger")
    if finger != TAIL_FINGER:
        raise ValueError(f"tail calibration only supports the {TAIL_FINGER} finger")
    lift = float(document.get("lift", 0.0))
    if not math.isfinite(lift) or lift < 0:
        raise ValueError("lift must be finite and non-negative")
    left_max_note = int(document.get("left_max_note", 59))

    raw_timing = document.get("timing") or {}
    timing = {
        "arm_lead_sec": _seconds(raw_timing.get("arm_lead_sec", 0.2), "arm_lead_sec"),
        "transition_sec": _seconds(raw_timing.get("transition_sec", 0.04), "transition_sec"),
        "prepare": {},
    }
    for name, prepare in (raw_timing.get("prepare") or {}).items():
        timing["prepare"][str(name)] = {
            "lead_sec": _seconds(prepare.get("lead_sec"), f"prepare.{name}.lead_sec"),
            "transition_sec": _seconds(prepare.get("transition_sec"),
                                       f"prepare.{name}.transition_sec"),
        }

    poses = {}
    for name, values in (document.get("poses") or {}).items():
        poses[str(name)] = {
            "arm_rad": _pose(values.get("arm_rad"), f"poses.{name}.arm_rad", 7),
            "positions": _pose(values.get("positions"), f"poses.{name}.positions", 20).tolist(),
        }

    leads = {int(key): _pose(value, f"leads.{key}", 2).tolist()
             for key, value in (document.get("leads") or {}).items()}

    events = []
    seen = set()
    for raw in document.get("events") or ():
        event_id = int(raw.get("id"))
        if event_id in seen:
            raise ValueError(f"duplicate tail event {event_id}")
        seen.add(event_id)
        pose = str(raw.get("pose"))
        if pose not in poses:
            raise ValueError(f"event {event_id} uses unknown pose {pose!r}")
        if pose not in timing["prepare"]:
            raise ValueError(f"event {event_id} pose {pose!r} has no prepare timing")
        if event_id not in leads:
            raise ValueError(f"event {event_id} has no command leads")
        start = float(raw.get("start"))
        end = float(raw.get("end"))
        if not (math.isfinite(start) and math.isfinite(end)) or start >= end:
            raise ValueError(f"event {event_id} needs a finite start before its end")
        events.append({
            "id": event_id, "note": int(raw.get("note")), "start": start, "end": end,
            "velocity": int(raw.get("velocity", 85)), "pose": pose,
            "transition_sec": _seconds(raw.get("transition_sec", timing["transition_sec"]),
                                       f"events.{event_id}.transition_sec"),
        })
    if not events:
        raise ValueError("tail calibration needs at least one event")
    events.sort(key=lambda item: (item["start"], item["id"]))
    return {"finger": finger, "left_max_note": left_max_note, "lift": lift,
            "timing": timing, "poses": poses, "leads": leads, "events": events}


def tail_events(spec):
    """Convert the calibration schedule into `piano_fingering/1` events."""
    return [{"id": item["id"], "hand": "right", "note": item["note"],
             "start": item["start"], "end": item["end"],
             "velocity": item["velocity"], "finger": spec["finger"]}
            for item in spec["events"]]


def lift_positions(spec, pose):
    """Raise the index channel of a press pose for the pre-press and release states."""
    lift = list(spec["poses"][pose]["positions"])
    lift[LIFT_CHANNEL] = min(255.0, lift[LIFT_CHANNEL] + spec["lift"])
    return lift


def detail_for(spec, event):
    """Motion and timing hints handed to the scheduler for one tail event."""
    prepare = spec["timing"]["prepare"][event["pose"]]
    return {"lift_positions": lift_positions(spec, event["pose"]),
            "arm_lead_sec": spec["timing"]["arm_lead_sec"],
            "prepare_lead_sec": prepare["lead_sec"],
            "prepare_transition_sec": prepare["transition_sec"],
            "transition_sec": event["transition_sec"],
            "command_leads_sec": list(spec["leads"][event["id"]])}


def schedule(model, spec, source=""):
    """Schedule the whole tail; return `(plan, planner)`, or `(None, planner)`."""
    planner = FingeringPlanner(model, fingering_mode="fixed", planning_budget_sec=1200.0)
    planner.started = time.monotonic()
    events = tail_events(spec)
    groups = group_events(events, model.chord_epsilon)
    if len(groups) != len(events):
        raise ValueError("tail calibration must not contain chords")
    state = planner._initial_state("right")
    for index, (event, group) in enumerate(zip(events, groups)):
        entry = spec["events"][index]
        pose = spec["poses"][entry["pose"]]
        candidate = Candidate(np.asarray(pose["arm_rad"], dtype=float),
                              list(pose["positions"]), (0, 0, 0), 0.0,
                              detail_for(spec, entry))
        assignments = [(event, spec["finger"])]
        updated, reason = planner._schedule_candidate(
            "right", group, state, assignments, assignments, candidate)
        print(event["id"], reason or "passed", flush=True)
        if updated is None:
            return None, planner
        state = updated
    return planner._build_plan("right", state, source, spec["left_max_note"]), planner


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tail", type=Path, default=None,
                        help="right tail calibration YAML; defaults to the packaged v29 file")
    parser.add_argument("--output", type=Path, default=Path("right_tail.performance.yaml"),
                        help="piano_performance/1 output YAML")
    parser.add_argument("--package", type=Path, default=None,
                        help="rm_mujoco source or share directory")
    args = parser.parse_args(argv)
    package = args.package or _default_package()
    tail = args.tail or package / "config/right_tail_v29.yaml"
    try:
        spec = load_tail(tail)
        model = PianoHandModel(package, package / "config/piano_scene.yaml",
                               package / "config/right_hand_piano_sim.yaml")
        plan, _ = schedule(model, spec, tail)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    if plan is None:
        print("ERROR the tail did not schedule completely", file=sys.stderr)
        return 1
    validate_plan(plan)
    write_plan(args.output, plan)
    print(f"WROTE {args.output} events={len(plan['hands']['right']['events'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
