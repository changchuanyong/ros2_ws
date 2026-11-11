#!/usr/bin/env python3
"""Retarget an existing performance plan onto a new scene without changing timing.

The score, fingering, hand states and arm-waypoint schedule are preserved; only
the joint values of each arm waypoint are re-solved for the new key positions.
This is the fast regression path for a layout change, while a full
`plan_performance.py` run remains the fallback if a waypoint cannot reach all
of its assigned notes with one pose.
"""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

try:
    from ament_index_python.packages import get_package_share_directory
except ImportError:
    get_package_share_directory = None

from rm_mujoco.fingering import (
    PLAY_R, PianoHandModel, orientation_rotation)
from rm_mujoco.performance import load_plan, validate_plan, write_plan


def default_package():
    if get_package_share_directory is not None:
        try:
            return Path(get_package_share_directory("rm_mujoco"))
        except Exception:
            pass
    return Path(__file__).resolve().parents[1]


def solve_waypoint(model, side, events, seed):
    prepared = []
    for event in events:
        finger = event["finger"]
        note = int(event["note"])
        hand20 = model.compose([finger], [note])
        desired_R = orientation_rotation((0, 0, 0), PLAY_R)
        model.prepare_tip(side, finger, hand20, desired_R)
        target = model.points[note - 21] + np.array([0.0, 0.0, -model.press_depth])
        prepared.append((event, finger, hand20, desired_R, target))
    solutions = []
    for event, finger, hand20, desired_R, target in prepared:
        solutions.extend(model.solve_arm_solutions(
            side, target, [seed, model.ready_arm_q[side]], hand20, desired_R, finger,
            posture={"previous": seed, "continuity_weight": 0.05}, limit=3))
    seen = []
    for solution in solutions:
        q = solution["q"]
        if any(np.max(np.abs(q - other)) < 1e-6 for other in seen):
            continue
        seen.append(q)
        ok = True
        for event, finger, hand20, _, _ in prepared:
            passed, _ = model.check_group(
                side, [(int(event["note"]), finger)], q, hand20, strict=True)
            if not passed:
                ok = False
                break
        if ok:
            return q, model.arm_posture(side, q)
    return None, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", type=Path, default=None)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--scene-config", type=Path, required=True)
    parser.add_argument("--pose-file", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--press-depth", type=float, default=0.0075)
    args = parser.parse_args(argv)
    package = (args.package or default_package()).resolve()
    scene = args.scene_config.resolve()
    pose = (args.pose_file or package / "config/right_hand_piano_sim.yaml").resolve()
    plan = load_plan(args.plan)
    model = PianoHandModel(package, scene, pose, press_depth=args.press_depth)
    failures = []
    for side, hand in plan["hands"].items():
        events = hand["events"]
        by_waypoint = {}
        for event in events:
            by_waypoint.setdefault(int(event["arm_waypoint"]), []).append(event)
        seed = model.ready_arm_q[side]
        for index, waypoint in enumerate(hand["arm_waypoints"]):
            group = by_waypoint.get(index, [])
            if not group:
                waypoint["joints"] = seed.tolist()
                continue
            q, posture = solve_waypoint(model, side, group, seed)
            if q is None:
                failures.append({"side": side, "waypoint": index,
                                 "notes": [event["note"] for event in group]})
                continue
            waypoint["joints"] = q.tolist()
            seed = q
            print(f"RETARGET {side} waypoint {index} notes={[e['note'] for e in group]} "
                  f"margin={posture['joint_margin_rad']:.3f}", flush=True)
        if failures:
            break
        hand["arm_start"] = hand["arm_waypoints"][0]["joints"]
        hand["posture"] = [model.arm_posture(side, item["joints"])
                           for item in hand["arm_waypoints"]]
    plan["metadata"]["layout"] = str(scene)
    plan["metadata"]["press_depth_m"] = args.press_depth
    if failures:
        print(json.dumps({"failures": failures}, indent=2))
        return 1
    validate_plan(plan)
    write_plan(args.output, plan)
    print(f"WROTE {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
