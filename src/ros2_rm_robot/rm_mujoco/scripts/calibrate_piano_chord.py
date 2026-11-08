#!/usr/bin/env python3
"""Calibrate a simulation-only 20-value hand state for a right-hand chord.

The executor is the ground truth: every candidate is replayed through the same
`PlanRunner` used by `run_performance.py`, so a static contact or a probe-only
result cannot be mistaken for a sounding chord.  The winning state is written
as a `chords:` override in a sim-specific pose YAML; the real calibration file
`right_hand_ode_to_joy.yaml` is never modified.

Usage:
    python3 calibrate_piano_chord.py \
      --score chord.fingering.yaml --plan chord.performance.yaml \
      --base-pose .../right_hand_ode_to_joy.yaml \
      --output-pose .../right_hand_piano_sim.yaml --output-dir /tmp/cal
"""

import argparse
import itertools
import json
from pathlib import Path
import sys

import numpy as np
import yaml

try:
    from ament_index_python.packages import get_package_share_directory
except ImportError:  # source-tree use before sourcing an install
    get_package_share_directory = None

from rm_mujoco.fingering import FingeringPlanner, PianoHandModel
from rm_mujoco.performance import FINGERS, load_events, load_plan
from run_performance import PlanRunner


def _default_package():
    if get_package_share_directory is not None:
        try:
            return Path(get_package_share_directory("rm_mujoco"))
        except Exception:
            pass
    return Path(__file__).resolve().parents[1]


def _chord_events(plan, side):
    events = plan["hands"][side]["events"]
    starts = sorted({event["start_sec"] for event in events})
    if not starts:
        raise ValueError("plan has no events")
    first = starts[0]
    chord = [event for event in events if abs(event["start_sec"] - first) < 1e-6]
    if not chord:
        raise ValueError("the first group is empty")
    return chord


def _compose_remaining(ready, deltas, fingers):
    values = np.asarray(ready, dtype=float).copy()
    for finger in fingers:
        values += deltas[finger]
    return np.clip(values, 0.0, 255.0)


def _mini_plan(base_plan, side, chord, press_state, ready, deltas, arm_joints=None):
    metadata = dict(base_plan["metadata"])
    hand = base_plan["hands"][side]
    chord_indices = {event["arm_waypoint"] for event in chord}
    arm_index = max(chord_indices)
    arm = hand["arm_waypoints"][arm_index]
    if arm_joints is not None:
        arm = {"joints": [float(value) for value in arm_joints]}
    press_time = min(event["start_sec"] for event in chord) - metadata["press_lead_sec"]
    press_fingers = sorted({event["finger"] for event in chord}, key=FINGERS.index)
    states = [{
        "time_sec": press_time,
        "pressed": press_fingers,
        "positions": press_state,
    }]
    for event in sorted(chord, key=lambda item: item["end_sec"]):
        remaining = [
            finger for finger in press_fingers
            if finger != event["finger"]]
        states.append({
            "time_sec": event["end_sec"] - metadata["release_lead_sec"],
            "pressed": remaining,
            "positions": _compose_remaining(ready, deltas, remaining),
        })
    states.append({
        "time_sec": max(event["end_sec"] for event in chord)
        - metadata["release_lead_sec"] + 0.2,
        "pressed": [],
        "positions": np.asarray(ready, dtype=float).tolist(),
    })
    events = []
    for event in chord:
        events.append({
            "id": event["id"], "note": event["note"],
            "start_sec": event["start_sec"], "end_sec": event["end_sec"],
            "velocity": event["velocity"], "finger": event["finger"],
            "prior_finger": event.get("prior_finger"),
            "arm_waypoint": 0,
        })
    return {
        "format": "piano_performance/1",
        "metadata": metadata,
        "hands": {
            side: {
                "ready_state": hand["ready_state"],
                "arm_start": arm["joints"],
                "arm_waypoints": [{
                    "time_sec": 0.0, "move_after_sec": 0.0,
                    "joints": arm["joints"]}],
                "hand_states": states,
                "events": events,
            }
        },
    }


def _score(report):
    if report["passed"]:
        return (0, 0.0)
    target_margin = 100.0
    other_peak = -100.0
    for note, angle in report["key_angles"].items():
        note = int(note)
        peak = angle["max_angle_deg"]
        threshold = angle["press_threshold_deg"]
        if any(event["note"] == note for event in report["expected_events"]):
            target_margin = min(target_margin, peak - threshold)
        else:
            other_peak = max(other_peak, peak - threshold)
    missing = len(report["missing"])
    unexpected = len(report["unexpected"])
    wrong = len(report["wrong_finger_contacts"])
    angles = len(report.get("angle_violations", []))
    return (1, missing + unexpected + wrong + angles,
            -target_margin, other_peak)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=None,
                        help="base performance plan; generated when omitted")
    parser.add_argument("--base-pose", type=Path, required=True)
    parser.add_argument("--output-pose", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--package", type=Path, default=None)
    parser.add_argument("--scene-config", type=Path, default=None)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--tempo-scale", type=float, default=1.0)
    parser.add_argument("--timing-tolerance", type=float, default=0.03)
    parser.add_argument("--press-depth", type=float, default=0.008,
                        help="IK target depth below the key surface, metres")
    args = parser.parse_args(argv)
    try:
        package = args.package or _default_package()
        scene = args.scene_config or package / "config/piano_scene.yaml"
        model_path = args.model or package / "models/rm_75_6fb_v_dual_l20.xml"
        document = yaml.safe_load(args.base_pose.read_text(encoding="utf-8"))
        poses = document["poses"]
        ready = np.asarray(poses["READY"]["positions"], dtype=float)
        press = {}
        for letter, finger in {"C": "thumb", "D": "index", "E": "middle",
                               "F": "ring", "G": "little"}.items():
            press[finger] = np.asarray(poses[f"PRESS_{letter}"]["positions"], dtype=float)
        deltas = {finger: values - ready for finger, values in press.items()}
        hand_model = None
        if args.plan is not None:
            plan = load_plan(args.plan)
        else:
            events = load_events(args.score)
            hand_model = PianoHandModel(package, scene, args.base_pose, press_depth=args.press_depth)
            planner = FingeringPlanner(hand_model, beam_width=4, candidate_limit=2)
            side = events["events"][0].get("hand") or "right"
            plan = planner.plan(events["events"], hand=side, source=args.score)
        if hand_model is None:
            hand_model = PianoHandModel(package, scene, args.base_pose, press_depth=args.press_depth)
        side = plan["metadata"]["hand"]
        chord = _chord_events(plan, side)
        fingers = sorted({event["finger"] for event in chord}, key=FINGERS.index)
        if len(fingers) not in (1, 2):
            raise ValueError(f"expected one or two fingers, got {fingers}")
        first = fingers[0]
        second = fingers[1] if len(fingers) > 1 else None
        arm_indices = {event["arm_waypoint"] for event in chord}
        chord_arm = np.asarray(
            plan["hands"][side]["arm_waypoints"][max(arm_indices)]["joints"],
            dtype=float)
        notes = [event["note"] for event in chord]
        args.output_dir.mkdir(parents=True, exist_ok=True)
        trials_path = args.output_dir / "trials.jsonl"
        if trials_path.exists():
            trials_path.unlink()
        if second is None:
            grid = itertools.product(
                (-12, -6, 0, 6, 12), (-6, 0, 6), (0,), (0,), ("full",))
        else:
            grid = itertools.product(
                (-12, -6, 0, 6, 12), (-6, 0, 6), (-6, 0, 6), (0,),
                ("full", "local"))
        dynamic_results = []
        trials = 0
        for middle_root, middle_tip, little_root, little_tip, mode in grid:
            e = press[first].copy()
            e[FINGERS.index(first)] += middle_root
            e[15 + FINGERS.index(first)] += middle_tip
            if second is None:
                state = e
            else:
                g = press[second].copy()
                g[FINGERS.index(second)] += little_root
                g[15 + FINGERS.index(second)] += little_tip
                if mode == "full":
                    state = ready + (e - ready) + (g - ready)
                else:
                    state = ready.copy()
                    for values, finger in ((e, first), (g, second)):
                        index = FINGERS.index(finger)
                        for slot in (index, 5 + index, 10 + index, 15 + index):
                            state[slot] += values[slot] - ready[slot]
            state = np.clip(state, 0.0, 255.0).tolist()
            if second is None:
                hand_model.note_overrides[chord[0]["note"], first] = np.asarray(
                    state, dtype=float)
            else:
                key = "+".join(fingers)
                hand_model.chord_overrides[key] = np.asarray(
                    state, dtype=float)
            hand_model._cache.clear()
            assignments = [(event, event["finger"]) for event in chord]
            candidate = hand_model.candidate_group(
                side, assignments, hand_model.ready_arm_q[side])
            probe_ok = candidate is not None
            probe_detail = (candidate.detail.get("probe", {}) if candidate
                            else {"error": "no reachable arm pose"})
            if candidate is not None:
                state = candidate.hand20
                arm_q = candidate.arm_q.copy()
            else:
                arm_q = chord_arm
            trials += 1
            dynamic_score = (
                (0,) if probe_ok else
                (1, len(probe_detail.get("missing", []))
                 + len(probe_detail.get("extra", []))
                 + len(probe_detail.get("stuck", [])),
                 len(probe_detail.get("missing", [])),
                 len(probe_detail.get("extra", [])),
                 len(probe_detail.get("stuck", []))))
            record = {
                "trial": trials, "middle_root": middle_root,
                "middle_tip": middle_tip, "little_root": little_root,
                "little_tip": little_tip, "mode": mode,
                "dynamic_ok": probe_ok, "dynamic_score": list(dynamic_score),
                "dynamic_detail": probe_detail,
            }
            with trials_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record) + "\n")
            print("TRIAL", trials, mode, middle_root, middle_tip,
                  little_root, probe_ok, dynamic_score, flush=True)
            dynamic_results.append((dynamic_score, state, arm_q, record))
        if not dynamic_results:
            raise ValueError("no candidate was evaluated")
        dynamic_results.sort(key=lambda item: item[0])
        best = None
        for dynamic_score, state, arm_q, record in dynamic_results[:8]:
            mini = _mini_plan(plan, side, chord, state, ready, deltas,
                              arm_joints=arm_q)
            runner = PlanRunner(
                mini, package, scene, model_path, args.tempo_scale,
                args.timing_tolerance, None, None)
            report = runner.run()
            full_score = _score(report)
            record.update({
                "full_passed": report["passed"], "full_score": list(full_score),
                "missing": len(report["missing"]),
                "unexpected": len(report["unexpected"]),
                "wrong_finger": len(report["wrong_finger_contacts"]),
                "key_angles": report["key_angles"],
            })
            with trials_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record) + "\n")
            print("FULL", record["trial"], record["mode"],
                  report["passed"], full_score, flush=True)
            if best is None or full_score < best[0]:
                best = (full_score, state, record)
            if report["passed"]:
                break
        if best is None:
            raise ValueError("no candidate was replayed")
        score, state, record = best
        document = yaml.safe_load(args.base_pose.read_text(encoding="utf-8"))
        if second is None:
            notes = document.setdefault("notes", {})
            key = str(chord[0]["note"])
            finger_key = f"{key}:{first}"
            existing = notes.get(key)
            if (finger_key in notes or (isinstance(existing, dict)
                                       and existing.get("finger") not in (None, first))):
                key = finger_key
            previous = notes.get(key)
            notes[key] = {
                **(previous if isinstance(previous, dict) else {}),
                "finger": first, "positions": [float(value) for value in state],
            }
            target_key = f"note {chord[0]['note']}"
        else:
            target_key = "+".join(fingers)
            chords = document.setdefault("chords", {})
            previous = chords.get(target_key)
            positions = [float(value) for value in state]
            chords[target_key] = ({**previous, "positions": positions}
                                  if isinstance(previous, dict) else positions)
        args.output_pose.parent.mkdir(parents=True, exist_ok=True)
        args.output_pose.write_text(
            yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
            encoding="utf-8")
        (args.output_dir / "best.json").write_text(
            json.dumps({"score": list(score), "record": record,
                        "target": target_key, "state": state}, indent=2),
            encoding="utf-8")
        print("WROTE", args.output_pose, "passed",
              record.get("full_passed", False), "score", score)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
