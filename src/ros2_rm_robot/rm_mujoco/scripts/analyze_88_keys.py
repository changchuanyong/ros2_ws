#!/usr/bin/env python3
"""Analyze 88-key single-note reachability for both RM75 arms.

The script checks real IK, strict key contacts (no extra keys or fingers),
joint-limit margins and, optionally, the continuous press/release probe for
every MIDI note 21-108.  It is intentionally independent of a score: this is
the layout/reachability oracle used before planning any music.

Usage:
    python3 analyze_88_keys.py --scene-config config/piano_scene_88key.yaml \
        --output .validation/reachability_88
"""

import argparse
import csv
import json
import math
from pathlib import Path
import sys

import numpy as np
import yaml

try:
    from ament_index_python.packages import get_package_share_directory
except ImportError:  # source-tree use before sourcing an install
    get_package_share_directory = None

from rm_mujoco.fingering import (
    PLAY_R, PianoHandModel, orientation_rotation)
from rm_mujoco.keyboard import KEY_NOTES
from rm_mujoco.performance import FINGERS

# Ordered from the cheapest flat-palm attempt to larger wrist adjustments.
ORIENTATION_LEVELS = (
    (((0, 0, 0),), ((0.0, 0.0), (0.0, -0.038))),
    (((-10, 0, 0), (10, 0, 0), (0, -6, 0), (0, 6, 0), (0, 0, -6), (0, 0, 6)),
     ((0.0, 0.0),)),
    (((-10, -6, 0), (10, -6, 0), (-20, 0, 0), (20, 0, 0)), ((0.0, 0.0),)),
)


def default_package():
    if get_package_share_directory is not None:
        try:
            return Path(get_package_share_directory("rm_mujoco"))
        except Exception:
            pass
    return Path(__file__).resolve().parents[1]


def min_clearance(model, side, arm_q, hand20):
    """Smallest geom distance from the active arm to the scene and other arm."""
    import mujoco as m

    data = model.reset_work()
    model.set_state(side, arm_q, hand20)
    m.mj_forward(model.model, data)
    other = "left" if side == "right" else "right"
    active = []
    obstacles = []
    for gid in range(model.model.ngeom):
        name = model.geom_names[gid]
        if name.startswith(side + "_") and any(
                token in name for token in ("Link", "flange", "l20", "camera")):
            active.append(gid)
        elif name.startswith(other + "_") and any(
                token in name for token in ("Link", "flange", "l20", "camera")):
            obstacles.append(gid)
        elif (name.startswith(("table_", "piano_"))
              and not name.startswith("piano_key_")):
            obstacles.append(gid)
    smallest = math.inf
    pair = None
    for first in active:
        for second in obstacles:
            value = float(m.mj_geomDistance(
                model.model, data, first, second, 0.30, None))
            if value < smallest:
                smallest = value
                pair = [model.geom_names[first], model.geom_names[second]]
    return (None if smallest is math.inf else smallest), pair


def try_finger(model, side, note, finger, seed, levels=(0, 1, 2)):
    """Return static candidates for one finger, best posture first."""
    hand20 = model.compose([finger], [note])
    point = model.points[note - KEY_NOTES.start]
    successes = []
    for level in levels:
        orientations, offsets = ORIENTATION_LEVELS[level]
        for orientation in orientations:
            desired_R = orientation_rotation(orientation, PLAY_R)
            model.prepare_tip(side, finger, hand20, desired_R)
            for dx, dy in offsets:
                target = point + np.array([dx, dy, -model.press_depth])
                solutions = model.solve_arm_solutions(
                    side, target, [seed, model.ready_arm_q[side]], hand20, desired_R,
                    finger, posture={"previous": seed, "continuity_weight": 0.05},
                    limit=2)
                for solution in solutions:
                    arm_q = solution["q"]
                    ok, detail = model.check_group(
                        side, [(note, finger)], arm_q, hand20, strict=True)
                    if not ok:
                        continue
                    metrics = model.arm_posture(side, arm_q)
                    if metrics["joint_margin_rad"] < 0.03:
                        continue
                    successes.append({
                        "finger": finger, "arm_q": arm_q.tolist(),
                        "orientation": orientation, "offset": [dx, dy],
                        "posture": metrics, "detail": detail,
                        "ik_score": solution["score"],
                    })
        if successes:
            break
    successes.sort(key=lambda item: (
        item["offset"] != [0.0, 0.0],
        model.posture_cost(item["posture"])
        + 0.05 * model.continuity_cost(np.asarray(item["arm_q"]), seed)))
    return successes


def analyze_note(model, side, note, seed, fingers, levels):
    results = []
    for finger in fingers:
        results.extend(try_finger(model, side, note, finger, seed, levels))
    results.sort(key=lambda item: (
        item["offset"] != [0.0, 0.0],
        model.posture_cost(item["posture"])
        + 0.05 * model.continuity_cost(np.asarray(item["arm_q"]), seed)))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", type=Path, default=None)
    parser.add_argument("--scene-config", type=Path, default=None)
    parser.add_argument("--pose-file", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--notes", default="21-108",
                        help="MIDI range, e.g. 21-108 or a comma list")
    parser.add_argument("--sides", default="left,right")
    parser.add_argument("--fingers", default=",".join(FINGERS))
    parser.add_argument("--dynamic", action="store_true",
                        help="run the continuous press/release probe for the best pose")
    parser.add_argument("--clearance", action="store_true",
                        help="measure minimum geom distance for the selected pose")
    parser.add_argument("--quick", action="store_true",
                        help="flat palm only, one finger per note (layout search)")
    parser.add_argument("--press-depth", type=float, default=0.008,
                        help="commanded fingertip depth below the key top (metres)")
    args = parser.parse_args(argv)
    package = (args.package or default_package()).resolve()
    scene = (args.scene_config or package / "config/piano_scene.yaml").resolve()
    pose = (args.pose_file or package / "config/right_hand_piano_sim.yaml").resolve()
    if "-" in args.notes:
        first, last = (int(value) for value in args.notes.split("-"))
        notes = list(range(first, last + 1))
    else:
        notes = [int(value) for value in args.notes.split(",")]
    sides = [value.strip() for value in args.sides.split(",") if value.strip()]
    fingers = [value.strip() for value in args.fingers.split(",") if value.strip()]
    if any(note not in KEY_NOTES for note in notes):
        parser.error("notes must be within MIDI 21-108")
    if any(finger not in FINGERS for finger in fingers):
        parser.error("unknown finger in --fingers")

    model = PianoHandModel(package, scene, pose, press_depth=args.press_depth)
    records = []
    for side in sides:
        seed = model.ready_arm_q[side]
        for note in notes:
            levels = (0,) if args.quick else (0, 1, 2)
            candidates = analyze_note(model, side, note, seed, fingers, levels)
            record = {
                "side": side, "note": int(note),
                "white": int(note % 12 in (0, 2, 4, 5, 7, 9, 11)),
                "static": bool(candidates),
                "fingers": sorted({item["finger"] for item in candidates}),
                "candidate_count": len(candidates),
            }
            chosen = None
            if candidates:
                if args.dynamic:
                    # A static contact is necessary but not sufficient; the key
                    # must also complete a real press and release without
                    # over-travel.  Try the best-ranked poses first.
                    for candidate in candidates[:6]:
                        arm_q = np.asarray(candidate["arm_q"], dtype=float)
                        hand20 = model.compose([candidate["finger"]], [note])
                        ok, detail = model.dynamic_probe(side, [note], arm_q, hand20)
                        if ok:
                            chosen = candidate
                            record["dynamic"] = True
                            record["dynamic_detail"] = {
                                key: detail.get(key) for key in
                                ("missing", "extra", "stuck", "angle_violations", "edges")}
                            break
                        record["dynamic_detail"] = {
                            key: detail.get(key) for key in
                            ("missing", "extra", "stuck", "angle_violations", "edges")}
                    if chosen is None:
                        record["dynamic"] = False
                else:
                    chosen = candidates[0]
                    record["dynamic"] = None
            else:
                record["dynamic"] = False
            if chosen is not None:
                record["arm_q"] = chosen["arm_q"]
                record["posture"] = chosen["posture"]
                record["orientation_deg"] = list(chosen["orientation"])
                record["offset_m"] = chosen["offset"]
                seed = np.asarray(chosen["arm_q"], dtype=float)
                if args.clearance:
                    value, pair = min_clearance(
                        model, side, seed, model.compose([chosen["finger"]], [note]))
                    record["min_clearance_m"] = value
                    record["clearance_pair"] = pair
            records.append(record)
            print(
                f"KEY {side:5s} {note:3d} static={record['static']} "
                f"fingers={','.join(record['fingers']) or '-'} "
                f"dynamic={record.get('dynamic')}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "reachability.json").write_text(
        json.dumps({"scene_config": str(scene), "pose_file": str(pose),
                    "dynamic": bool(args.dynamic), "records": records}, indent=2),
        encoding="utf-8")
    with (args.output / "reachability.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["side", "note", "static", "dynamic", "fingers",
                         "elbow_drop_m", "elbow_lateral_m", "joint_margin_rad",
                         "min_clearance_m"])
        for record in records:
            posture = record.get("posture", {})
            writer.writerow([
                record["side"], record["note"], record["static"],
                record.get("dynamic", ""), "|".join(record["fingers"]),
                posture.get("elbow_drop_m"), posture.get("elbow_lateral_m"),
                posture.get("joint_margin_rad"), record.get("min_clearance_m")])
    make_plot(records, args.output)
    covered = {record["note"] for record in records if record.get("dynamic")
               or (not args.dynamic and record["static"])}
    print(f"COVERAGE {len(covered)}/{len(notes)} notes={min(notes)}-{max(notes)}")
    return 0


def make_plot(records, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    notes = sorted({record["note"] for record in records})
    sides = sorted({record["side"] for record in records})
    values = np.zeros((len(sides), len(notes)))
    for row, side in enumerate(sides):
        by_note = {record["note"]: record for record in records if record["side"] == side}
        for column, note in enumerate(notes):
            record = by_note[note]
            if record.get("dynamic"):
                values[row, column] = 2
            elif record["static"]:
                values[row, column] = 1
    figure, axis = plt.subplots(figsize=(16, 3.2))
    image = axis.imshow(values, aspect="auto", interpolation="nearest",
                        cmap=ListedColormap(["#c0392b", "#f1c40f", "#27ae60"]),
                        vmin=0, vmax=2)
    axis.set_yticks(range(len(sides)))
    axis.set_yticklabels([side.capitalize() for side in sides])
    ticks = [index for index, note in enumerate(notes) if note % 12 == 0]
    axis.set_xticks(ticks)
    axis.set_xticklabels([f"C{note // 12 - 1}" for note in notes
                          if note % 12 == 0], rotation=0, fontsize=7)
    axis.set_xlabel("MIDI note (21 A0 - 108 C8)")
    axis.set_title("88-key reachability: green dynamic, yellow static, red unreachable")
    figure.colorbar(image, ax=axis, ticks=[0, 1, 2], shrink=0.8,
                    label="status")
    figure.tight_layout()
    figure.savefig(output / "reachability_heatmap.png", dpi=160)
    plt.close(figure)

    figure, axes = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
    for side in sides:
        selected = sorted((record for record in records
                           if record["side"] == side and record.get("posture")),
                          key=lambda item: item["note"])
        axes[0].plot([item["note"] for item in selected],
                     [item["posture"]["elbow_drop_m"] for item in selected],
                     label=f"{side} elbow drop")
        axes[0].plot([item["note"] for item in selected],
                     [item["posture"]["joint_margin_rad"] for item in selected],
                     label=f"{side} joint margin (rad)")
    axes[0].axhline(0.10, color="black", linestyle=":", linewidth=1)
    axes[0].axhline(0.25, color="grey", linestyle=":", linewidth=1)
    axes[0].set_ylabel("metres / rad")
    axes[0].legend(fontsize=7, ncol=2)
    axes[0].grid(True, alpha=0.25)
    for side in sides:
        selected = sorted((record for record in records
                           if record["side"] == side and record.get("posture")),
                          key=lambda item: item["note"])
        axes[1].plot([item["note"] for item in selected],
                     [item["posture"]["extension"] for item in selected],
                     label=f"{side} extension")
    axes[1].set_xlabel("MIDI note")
    axes[1].set_ylabel("reach fraction")
    axes[1].legend(fontsize=7)
    axes[1].grid(True, alpha=0.25)
    figure.tight_layout()
    figure.savefig(output / "posture_metrics.png", dpi=160)
    plt.close(figure)


if __name__ == "__main__":
    sys.exit(main())
