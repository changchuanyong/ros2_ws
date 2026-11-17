#!/usr/bin/env python3
"""Prepare one official SKY-Piano explorer sample for robot retargeting."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE.parent / "rm_piano_player"))

from rm_mujoco.skypiano import (  # noqa: E402
    curriculum_fragments, note_sequence_bytes, prepare_sample, sha256, transform_targets,
)
from rm_piano_player.midi_file import read_score  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=float, required=True,
                        help="explorer samples: 30; do not copy fingering.json's 120")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--piece", required=True)
    parser.add_argument("--split", choices=("train", "valid", "test"), required=True)
    parser.add_argument("--fingering-details", type=Path,
                        help="optional fingering.json; must match this sample exactly")
    parser.add_argument("--curriculum-max-notes", type=int, default=8,
                        help="maximum notes per intact, fully labeled overlap component")
    parser.add_argument("--world-from-keyboard", type=Path,
                        help="JSON 4x4 rigid transform, translation in metres")
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError(f"output already exists: {args.output}; use a new directory")
        result = prepare_sample(args.sample, read_score(args.sample / "midi.mid"),
                                args.fps, args.subject, args.piece, args.split,
                                args.fingering_details)
        score, labels, arrays, windows, report = result
        fragments = curriculum_fragments(score["events"], args.curriculum_max_notes)
        report["curriculum_fragments"] = len(fragments)
        report["curriculum_max_notes"] = args.curriculum_max_notes
        world_targets = None
        if args.world_from_keyboard is not None:
            calibration = json.loads(args.world_from_keyboard.read_text(encoding="utf-8-sig"))
            features = {key: value for key, value in arrays.items()
                        if key.startswith(("left_", "right_"))}
            world_targets = transform_targets(features, calibration)
            report["calibration"] = {"path": str(args.world_from_keyboard.resolve()),
                                     "sha256": sha256(args.world_from_keyboard),
                                     "world_from_keyboard": calibration}
        args.output.mkdir(parents=True)
        (args.output / "score.fingering.yaml").write_text(
            yaml.safe_dump(score, sort_keys=False), encoding="utf-8")
        for name, value in (("labels", labels), ("windows", windows), ("report", report),
                            ("curriculum", fragments)):
            (args.output / f"{name}.json").write_text(
                json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        np.savez_compressed(args.output / "motion.npz", **arrays)
        if fragments:
            (args.output / "curriculum").mkdir()
        for index, fragment in enumerate(fragments):
            (args.output / "curriculum" / f"{index:04d}.proto").write_bytes(
                note_sequence_bytes(fragment["events"]))
        if world_targets is not None:
            np.savez_compressed(args.output / "human_world_targets.npz",
                                time_sec=arrays["time_sec"], **world_targets)
    except (OSError, ValueError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({key: report[key] for key in (
        "sample", "frames", "notes", "labeled_notes", "windows",
        "isolated_in_hand_windows", "fully_observed_windows", "curriculum_fragments",
        "robot_expert_eligible")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
