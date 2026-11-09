#!/usr/bin/env python3
"""Prepare traceable original-speed PianoVAM excerpts with physical references.

Candidate rules are identical in train/validation/test. Every attempted window
and rejection remains in attempts.json; a failed recording is never relabeled.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from import_pianovam import read_fingering, to_events, validate_rows  # noqa: E402
from train_piano_rl import default_package, sha256  # noqa: E402


def candidate_windows(rows):
    """Rank contiguous right-hand phrases; preserve all onsets and key offsets."""
    right = sorted((row for row in rows if row["hand"] == "R"),
                   key=lambda row: (row["onset"], row["note"]))
    candidates = []
    previous_end = []
    held_until = -float("inf")
    for row in right:
        previous_end.append(held_until)
        held_until = max(held_until, row["key_offset"])
    familiar = {(65, "1"), (67, "2"), (70, "3"), (72, "2"),
                (74, "2"), (76, "3"), (77, "4"), (79, "5")}
    for count in (3, 2, 1):
        for first in range(len(right) - count + 1):
            window = right[first:first + count]
            if any(not 60 <= row["note"] <= 81 or row["finger"] not in "12345"
                   or row["key_offset"] - row["onset"] < 0.14
                   or row["key_offset"] - row["onset"] > 1.0 for row in window):
                continue
            if previous_end[first] > window[0]["onset"] - 0.08:
                continue
            after = first + count
            if after < len(right) and right[after]["onset"] < max(
                    row["key_offset"] for row in window) - 1e-6:
                continue
            if any(b["onset"] - a["key_offset"] < 0.12
                   for a, b in zip(window, window[1:])):
                continue
            if window[-1]["key_offset"] - window[0]["onset"] > 3.0:
                continue
            if max(row["note"] for row in window) - min(row["note"] for row in window) > 7:
                continue
            score = count * 100 + sum((row["note"], row["finger"]) in familiar
                                      for row in window) * 10
            candidates.append((score, first, window))
    return [window for _, _, window in sorted(candidates, key=lambda item: (-item[0], item[1]))]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts-per-recording", type=int, default=8)
    args = parser.parse_args(argv)
    package = (args.package or default_package()).resolve()
    dataset = args.dataset.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metadata_path = dataset / "metadata.json"
    records = {row["record_time"]: row for row in json.loads(
        metadata_path.read_text(encoding="utf-8")).values()}
    manifest = {"format": "piano_rl_dataset/2", "dataset": str(dataset),
                "metadata_sha256": sha256(metadata_path),
                "train": [], "validation": [], "test": []}
    attempts = []
    failures = []
    process_env = dict(os.environ, PYTHONPATH=str(package), PYTHONDONTWRITEBYTECODE="1")
    for source in sorted((dataset / "Fingering_GT").glob("*.tsv")):
        split = records[source.stem]["split"]
        phase = {"train": "train", "ext-train": "train",
                 "valid": "validation", "test": "test"}.get(split)
        if phase is None:
            continue
        windows = candidate_windows(read_fingering(source))
        # Reserve attempts for all three phrase lengths instead of exhausting
        # the budget on complex windows that the current reference planner lacks.
        selected = []
        for length in (3, 2, 1):
            selected.extend([window for window in windows if len(window) == length][:3])
        accepted = False
        for index, window in enumerate(selected[:args.attempts_per_recording]):
            folder = output / phase / source.stem / str(index)
            folder.mkdir(parents=True)
            origin = window[0]["onset"]
            events = to_events(validate_rows(window), "right")
            for event in events:
                event["start"] -= origin
                event["end"] -= origin
            score = folder / "score.yaml"
            score.write_text(yaml.safe_dump({"format": "piano_fingering/1",
                                            "source": str(source), "events": events},
                                           sort_keys=False), encoding="utf-8")
            plan = folder / "plan.yaml"
            command = [sys.executable, str(package / "scripts/plan_performance.py"),
                       "--package", str(package), "--score", str(score), "--output", str(plan),
                       "--hand", "right", "--fingering-mode", "fixed", "--tempo-scale", "1",
                       "--beam-width", "2", "--candidate-limit", "2",
                       "--planning-budget-sec", "15"]
            row = {"source": source.name, "split": split, "phase": phase,
                   "origin_sec": origin, "notes": len(events), "folder": str(folder)}
            try:
                with (folder / "planning.log").open("w") as log:
                    result = subprocess.run(command, env=process_env, stdout=log,
                                            stderr=subprocess.STDOUT, timeout=45)
                row["plan_exit"] = result.returncode
                if result.returncode == 0:
                    with (folder / "playback.log").open("w") as log:
                        result = subprocess.run([
                            sys.executable, str(package / "scripts/run_performance.py"),
                            "--package", str(package), "--plan", str(plan),
                            "--output", str(folder / "playback")], env=process_env,
                            stdout=log, stderr=subprocess.STDOUT, timeout=30)
                    row["playback_exit"] = result.returncode
                    report_path = folder / "playback/report.json"
                    if report_path.is_file():
                        report = json.loads(report_path.read_text())
                        row.update(passed=report["passed"], missing=len(report["missing"]),
                                   unexpected=len(report["unexpected"]),
                                   angle_violations=report["angle_violations"])
                    if result.returncode == 0 and row.get("passed"):
                        manifest[phase].append({
                            "source": str(source.relative_to(dataset)),
                            "source_sha256": sha256(source), "origin_sec": origin,
                            "plan": str(plan.relative_to(output)), "plan_sha256": sha256(plan),
                            "notes": len(events), "piece": records[source.stem].get("piece")})
                        accepted = True
                else:
                    row["failure"] = (folder / "planning.log").read_text()[-1500:]
            except subprocess.TimeoutExpired:
                row["failure"] = "candidate exceeded the frozen wall-clock budget"
            attempts.append(row)
            (output / "attempts.json").write_text(json.dumps(attempts, indent=2), encoding="utf-8")
            print("CANDIDATE", json.dumps(row), flush=True)
            if accepted:
                break
        if not accepted:
            failures.append({"source": source.name, "split": split,
                             "eligible_windows": len(windows), "attempted": len(selected[:args.attempts_per_recording])})
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "coverage.json").write_text(json.dumps({
        "accepted_recordings": {phase: len(manifest[phase]) for phase in ["train", "validation", "test"]},
        "rejected_recordings": failures, "scope": "feasible right-hand short excerpts; not full-song coverage",
    }, indent=2), encoding="utf-8")
    return 0 if all(manifest[phase] for phase in ["train", "validation", "test"]) else 2


if __name__ == "__main__":
    sys.exit(main())
