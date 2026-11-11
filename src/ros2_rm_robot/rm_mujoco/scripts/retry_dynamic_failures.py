#!/usr/bin/env python3
"""Retry dynamic press/release checks for keys that were only statically reachable.

The first pass deliberately limits dynamic probes to the best poses.  Black keys
and workspace-edge keys often need the front-of-key offset or a different wrist
tilt, so this pass exhausts the static candidates and, when necessary, a slightly
shallower command depth before declaring a key unreachable.
"""

import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "scripts"))

from analyze_88_keys import analyze_note, make_plot  # noqa: E402
from rm_mujoco.fingering import PianoHandModel  # noqa: E402
from rm_mujoco.performance import FINGERS  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--scene-config", type=Path, required=True)
    parser.add_argument("--pose-file", type=Path, default=None)
    parser.add_argument("--reachability", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--primary-depth", type=float, default=0.0075)
    parser.add_argument("--fallback-depth", type=float, default=0.0070)
    args = parser.parse_args(argv)
    package = args.package.resolve()
    scene = args.scene_config.resolve()
    pose = (args.pose_file or package / "config/right_hand_piano_sim.yaml").resolve()
    document = json.loads(args.reachability.read_text(encoding="utf-8"))
    records = document["records"]
    models = {
        args.primary_depth: PianoHandModel(package, scene, pose,
                                           press_depth=args.primary_depth),
        args.fallback_depth: PianoHandModel(package, scene, pose,
                                            press_depth=args.fallback_depth),
    }
    by_side_note = {(record["side"], record["note"]): record for record in records}

    def nearest_seed(side, note):
        choices = [record for (other_side, other_note), record in by_side_note.items()
                   if other_side == side and record.get("arm_q")
                   and other_note != note]
        if not choices:
            return models[args.primary_depth].ready_arm_q[side]
        record = min(choices, key=lambda item: abs(item["note"] - note))
        return np.asarray(record["arm_q"], dtype=float)

    retried = 0
    for record in records:
        if record.get("dynamic"):
            continue
        side, note = record["side"], record["note"]
        seed = nearest_seed(side, note)
        chosen = None
        used_depth = args.primary_depth
        candidates = analyze_note(models[args.primary_depth], side, note, seed,
                                  list(FINGERS), (0, 1, 2))
        for candidate in candidates:
            model = models[args.primary_depth]
            hand20 = model.compose([candidate["finger"]], [note])
            ok, detail = model.dynamic_probe(
                side, [note], np.asarray(candidate["arm_q"], dtype=float), hand20)
            if ok:
                chosen, used_depth = candidate, args.primary_depth
                record["dynamic_detail"] = {
                    key: detail.get(key) for key in
                    ("missing", "extra", "stuck", "angle_violations", "edges")}
                break
        if chosen is None:
            candidates = analyze_note(models[args.fallback_depth], side, note, seed,
                                      list(FINGERS), (0, 1, 2))
            for candidate in candidates:
                model = models[args.fallback_depth]
                hand20 = model.compose([candidate["finger"]], [note])
                ok, detail = model.dynamic_probe(
                    side, [note], np.asarray(candidate["arm_q"], dtype=float), hand20)
                if ok:
                    chosen, used_depth = candidate, args.fallback_depth
                    record["dynamic_detail"] = {
                        key: detail.get(key) for key in
                        ("missing", "extra", "stuck", "angle_violations", "edges")}
                    break
        if chosen is None:
            record["dynamic"] = False
            record["retry"] = "no dynamic candidate"
            print(f"RETRY {side} {note} still unreachable", flush=True)
            continue
        record.update({
            "static": True, "dynamic": True, "dynamic_finger": chosen["finger"],
            "arm_q": chosen["arm_q"], "posture": chosen["posture"],
            "orientation_deg": list(chosen["orientation"]),
            "offset_m": chosen["offset"], "press_depth_m": used_depth,
            "retry": "dynamic candidate",
        })
        record["fingers"] = sorted(set(record.get("fingers", [])) | {chosen["finger"]})
        retried += 1
        print(f"RETRY {side} {note} pass finger={chosen['finger']} "
              f"offset={chosen['offset']} depth={used_depth}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "reachability.json").write_text(
        json.dumps({"scene_config": str(scene), "pose_file": str(pose),
                    "dynamic": True, "records": records}, indent=2), encoding="utf-8")
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
    covered = {record["note"] for record in records if record.get("dynamic")}
    print(f"RETRIED {retried} COVERAGE {len(covered)}/88")
    return 0


if __name__ == "__main__":
    sys.exit(main())
