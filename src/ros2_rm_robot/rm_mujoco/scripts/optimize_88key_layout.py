#!/usr/bin/env python3
"""Fast geometric layout search for full 88-key dual-arm coverage.

This is the coarse stage of the layout search: it uses the real 88-key press
points and the RM75 shoulder positions, rejects layouts whose nearest shoulder
is beyond the arm's reach envelope, and ranks the rest by coverage, mid-keyboard
overlap and worst-case reach margin.  The best candidates can then be passed to
`analyze_88_keys.py` for full IK/dynamic verification.

Usage:
    python3 optimize_88key_layout.py --base-scene config/piano_scene_88key.yaml \
        --output .validation/layout_search
"""

import argparse
import copy
import itertools
import json
import math
from pathlib import Path
import sys

import yaml

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.keyboard import KEY_NOTES  # noqa: E402
from rm_mujoco.scene import key_positions, load_layout  # noqa: E402

# Shoulder-to-fingertip envelope of the RM75 + L20 chain.  The exact IK check
# still decides reachability; these bounds only remove hopeless layouts.
MAX_REACH = 0.80
MIN_REACH = 0.22
OVERLAP_RANGE = range(55, 73)


def evaluate(layout):
    frame = layout["piano_frame"]["position"]
    points = [tuple(point[index] + frame[index] for index in range(3))
              for point in key_positions(layout)]
    distances = {}
    for side in ("left", "right"):
        base = layout["bases"][side]["position"]
        shoulder = (base[0], base[1], base[2] + 0.2405)
        distances[side] = [math.dist(shoulder, point) for point in points]
    nearest = [min(distances["left"][index], distances["right"][index])
               for index in range(len(points))]
    covered = [note for note, value in zip(KEY_NOTES, nearest) if value <= MAX_REACH]
    left = {note for note, value in zip(KEY_NOTES, distances["left"]) if value <= MAX_REACH}
    right = {note for note, value in zip(KEY_NOTES, distances["right"]) if value <= MAX_REACH}
    overlap = len(left & right & set(OVERLAP_RANGE))
    worst = max(nearest)
    return {
        "coverage": len(covered),
        "uncovered": [int(note) for note in KEY_NOTES if note not in covered],
        "left_count": len(left), "right_count": len(right),
        "overlap": overlap, "worst_nearest_m": round(worst, 4),
        "max_nearest_note": int(KEY_NOTES[nearest.index(worst)]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-x", default="0.18,0.20,0.22,0.24,0.26")
    parser.add_argument("--base-y", default="-0.16,-0.12,-0.08,-0.04,0.00")
    parser.add_argument("--piano-y", default="0.35,0.40,0.45,0.50,0.55")
    parser.add_argument("--piano-z", default="0.72,0.74,0.76")
    parser.add_argument("--base-yaw-deg", default="-15,0,15")
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args(argv)
    base = yaml.safe_load(args.base_scene.read_text(encoding="utf-8"))
    values = {
        "base_x": [float(value) for value in args.base_x.split(",")],
        "base_y": [float(value) for value in args.base_y.split(",")],
        "piano_y": [float(value) for value in args.piano_y.split(",")],
        "piano_z": [float(value) for value in args.piano_z.split(",")],
        "yaw": [math.radians(float(value)) for value in args.base_yaw_deg.split(",")],
    }
    results = []
    for base_x, base_y, piano_y, piano_z, yaw in itertools.product(
            values["base_x"], values["base_y"], values["piano_y"],
            values["piano_z"], values["yaw"]):
        layout = copy.deepcopy(base)
        layout["bases"]["left"]["position"] = [-base_x, base_y, base["bases"]["left"]["position"][2]]
        layout["bases"]["right"]["position"] = [base_x, base_y, base["bases"]["right"]["position"][2]]
        layout["bases"]["left"]["rpy"] = [0.0, 0.0, yaw]
        layout["bases"]["right"]["rpy"] = [0.0, 0.0, -yaw]
        layout["piano_frame"]["position"] = [0.0, piano_y, piano_z]
        # The table must still support the base plates; move its centre with
        # the arms only when the requested base row leaves the table.
        layout["table"]["position"][1] = base_y - 0.30
        metrics = evaluate(layout)
        results.append({"base_x": base_x, "base_y": base_y,
                        "piano_y": piano_y, "piano_z": piano_z,
                        "base_yaw_deg": round(math.degrees(yaw), 2), **metrics,
                        "layout": layout})
    results.sort(key=lambda item: (-item["coverage"], -item["overlap"],
                                   item["worst_nearest_m"]))
    args.output.mkdir(parents=True, exist_ok=True)
    summary = [{key: value for key, value in item.items() if key != "layout"}
               for item in results]
    (args.output / "layout_search.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    for item in results[:args.top]:
        print(json.dumps({key: value for key, value in item.items()
                          if key != "layout"}, sort_keys=True))
    if results:
        best = results[0]
        (args.output / "piano_scene_best.yaml").write_text(
            yaml.safe_dump(best["layout"], sort_keys=False), encoding="utf-8")
        print(f"WROTE {args.output / 'piano_scene_best.yaml'} "
              f"coverage={best['coverage']} overlap={best['overlap']} "
              f"worst={best['worst_nearest_m']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
