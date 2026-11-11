#!/usr/bin/env python3
"""Build PianoVAM direct-RL tasks without a robot performance plan.

The output is `piano_rl_tasks/1` JSON: absolute PianoVAM event times, relative
frame targets, finger hints and source/split provenance.  It never calls the
traditional planner and never creates `piano_performance/1`.

Usage:
    python3 prepare_pianovam_tasks.py --fingering song.tsv --split train \
        --output song.tasks.json
    python3 prepare_pianovam_tasks.py --dataset dataset --output .validation/tasks
"""

import argparse
import json
import os
from pathlib import Path
import sys

def _package_root():
    root = Path(__file__).resolve().parents[1]
    if (root / "models").is_dir():
        return root
    try:
        from ament_index_python.packages import get_package_share_directory
        return Path(get_package_share_directory("rm_mujoco"))
    except Exception:
        return root


PACKAGE = _package_root()
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "scripts"))

from import_pianovam import read_fingering, to_events, validate_rows  # noqa: E402
from rm_mujoco.pianovam_corpus import (  # noqa: E402
    MANIFEST_FORMAT, metadata_recordings, piece_identity, sha256, verify_split_isolation,
)
from rm_mujoco.pianovam_tasks import (  # noqa: E402
    FORMAT, LOOKAHEAD_SEC, SPLITS, NoTaskWindows, PianoVamTaskSet, build_task_set,
    summarize_task_set, write_task_set,
)


def _window_values(text):
    values = sorted({int(value) for value in text.split(",") if value.strip()})
    if not values or any(value <= 0 for value in values):
        raise ValueError("--window-notes must contain positive integers")
    return values


def _manifest_path(path, root):
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:
        return path.as_posix()


def _tasks_from_file(path, split, hand, left_max_note, window_values,
                     stride_sec, frame_dt, tail_sec, lead_in_sec, max_tasks,
                     allow_carry_in, complete_phrases=False):
    rows = validate_rows(read_fingering(path), path)
    events = to_events(rows, hand_filter=hand, left_max_note=left_max_note)
    tasks = []
    seen = set()
    digest = sha256(path)
    for window_notes in window_values:
        try:
            task_set = build_task_set(
                events, source=path, source_sha256=digest, split=split,
                left_max_note=left_max_note, window_notes=window_notes,
                stride_sec=stride_sec, tail_sec=tail_sec, lead_in_sec=lead_in_sec,
                frame_dt=frame_dt, allow_carry_in=allow_carry_in,
                complete_phrases=complete_phrases, lookahead_sec=LOOKAHEAD_SEC,
                max_tasks=max_tasks)
        except NoTaskWindows:
            continue
        for task in task_set.tasks:
            key = (task.origin_sec, tuple(event.id for event in task.events))
            if key in seen:
                continue
            seen.add(key)
            tasks.append(task)
    tasks.sort(key=lambda task: (task.origin_sec, task.id))
    if max_tasks:
        tasks = tasks[:max_tasks]
    if not tasks:
        raise NoTaskWindows(f"{path}: no task windows")
    return PianoVamTaskSet(path.as_posix(), digest, split, left_max_note,
                           frame_dt, LOOKAHEAD_SEC, tuple(tasks))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fingering", type=Path, help="one PianoVAM TSV")
    parser.add_argument("--dataset", type=Path, help="dataset with metadata.json")
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--fingering-dir", default="Fingering_GT")
    parser.add_argument("--split", choices=SPLITS, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hand", choices=("all", "left", "right"), default="all")
    parser.add_argument("--left-max-note", type=int, default=59)
    parser.add_argument("--window-notes", default="1",
                        help="comma-separated onset-group counts, e.g. 1,2,4")
    parser.add_argument("--stride-sec", type=float, default=0.0)
    parser.add_argument("--frame-dt", type=float, default=0.02)
    parser.add_argument("--tail-sec", type=float, default=0.6)
    parser.add_argument("--lead-in-sec", type=float, default=0.0,
                        help="prepend preparation time before the first onset")
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--allow-carry-in", action="store_true")
    parser.add_argument("--complete-phrases", action="store_true",
                        help="require closed score boundaries (always used with --dataset)")
    args = parser.parse_args(argv)
    try:
        windows = _window_values(args.window_notes)
    except ValueError as error:
        parser.error(str(error))
    if args.max_tasks < 0:
        parser.error("--max-tasks must be non-negative")
    if bool(args.fingering) == bool(args.dataset):
        parser.error("provide exactly one of --fingering or --dataset")
    if args.fingering and args.split is None:
        parser.error("--split is required with --fingering")
    if args.fingering and args.metadata:
        parser.error("--metadata is only used with --dataset")
    if (args.dataset or args.complete_phrases) and args.allow_carry_in:
        parser.error("complete phrases cannot use --allow-carry-in")

    if args.fingering:
        try:
            task_set = _tasks_from_file(
                args.fingering.resolve(), args.split, args.hand, args.left_max_note,
                windows, args.stride_sec, args.frame_dt, args.tail_sec,
                args.lead_in_sec, args.max_tasks, args.allow_carry_in, args.complete_phrases)
            write_task_set(args.output, task_set)
            print(f"WROTE {args.output} {json.dumps(summarize_task_set(task_set))}")
            return 0
        except (OSError, ValueError) as error:
            print(f"ERROR {error}", file=sys.stderr)
            return 1

    dataset = args.dataset.resolve()
    metadata_path = (args.metadata or dataset / "metadata.json").resolve()
    try:
        by_recording = metadata_recordings(metadata_path)
    except (OSError, ValueError) as error:
        print(f"ERROR cannot read metadata {metadata_path}: {error}", file=sys.stderr)
        return 1
    output = args.output.resolve()
    if (output / "manifest.json").exists():
        parser.error("use a new output directory for a frozen manifest")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": MANIFEST_FORMAT,
        "dataset": _manifest_path(dataset, output),
        "metadata": _manifest_path(metadata_path, output),
        "metadata_sha256": sha256(metadata_path),
        "hand": args.hand,
        "splits": {},
    }
    summary = {"format": FORMAT, "splits": {}, "sources": [], "skipped": []}
    errors = []
    identities = []
    for source in sorted((dataset / args.fingering_dir).glob("*.tsv")):
        row = by_recording.get(source.stem)
        if not isinstance(row, dict):
            summary["skipped"].append(
                {"source": source.name, "reason": "not listed in metadata"})
            continue
        if row.get("split") not in SPLITS:
            errors.append(f"{source.name}: unknown metadata split {row.get('split')!r}")
            continue
        split = row["split"]
        try:
            composer, piece = piece_identity(row)
            task_set = _tasks_from_file(
                source, split, args.hand, args.left_max_note, windows,
                args.stride_sec, args.frame_dt, args.tail_sec,
                args.lead_in_sec, args.max_tasks, False, complete_phrases=True)
        except NoTaskWindows:
            summary["skipped"].append(
                {"source": source.name, "reason": "no complete phrase for the requested sizes"})
            continue
        except (OSError, ValueError) as error:
            errors.append(f"{source.name}: {error}")
            continue
        split_dir = output / split
        split_dir.mkdir(parents=True, exist_ok=True)
        target = split_dir / f"{source.stem}.tasks.json"
        write_task_set(target, task_set)
        relative = target.relative_to(output).as_posix()
        identities.append((split, source.stem, task_set.source_sha256, composer, piece))
        manifest["splits"].setdefault(split, []).append({
            "recording": source.stem,
            "composer": composer,
            "piece": piece,
            "source": source.relative_to(dataset).as_posix(),
            "source_sha256": task_set.source_sha256,
            "tasks": relative,
            "tasks_sha256": sha256(target),
            "task_count": task_set.task_count,
        })
        summary["sources"].append({
            "source": str(source.relative_to(dataset)),
            "split": split,
            "file": relative,
            **summarize_task_set(task_set),
        })
        print(f"WROTE {target} {json.dumps(summarize_task_set(task_set))}")
    for split, entries in manifest["splits"].items():
        summary["splits"][split] = {
            "sources": len(entries),
            "tasks": sum(entry["task_count"] for entry in entries),
        }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n",
                                         encoding="utf-8")
    if errors:
        print("ERROR " + "; ".join(errors), file=sys.stderr)
        return 2
    if not summary["splits"]:
        print("ERROR no source produced tasks", file=sys.stderr)
        return 1
    try:
        verify_split_isolation(identities)
    except ValueError as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                          encoding="utf-8")
    print(f"WROTE {output} {json.dumps(summary['splits'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
