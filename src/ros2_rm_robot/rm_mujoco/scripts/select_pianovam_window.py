#!/usr/bin/env python3
"""Select a fixed, reproducible PianoVAM right-hand window for P0 baseline.

The importer's `--limit` can cut a chord, so P0 uses this selector instead:
it keeps complete onset groups, requires 20-30 right-hand note events and at
least three 50-150 ms physical gaps, and records the source hash and timing
mapping.  Output is a normal `piano_fingering/1` file plus a JSON map.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

FINGERS = ["thumb", "index", "middle", "ring", "little"]
HANDS = {"R": "right", "L": "left"}


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_groups(path, hand):
    events = []
    with path.open(encoding="utf-8") as stream:
        header = stream.readline().split()
        expected = ["onset", "key_offset", "frame_offset", "note",
                    "velocity", "hand", "finger"]
        if header != expected:
            raise ValueError(f"{path}: unexpected header {header}")
        for line in stream:
            parts = line.split()
            if not parts:
                continue
            if len(parts) != 7:
                raise ValueError(f"{path}: bad row {line!r}")
            row_hand = HANDS.get(parts[5])
            if row_hand != hand:
                continue
            try:
                finger = int(parts[6])
            except ValueError:
                finger = None
            events.append({
                "onset": float(parts[0]),
                "key_offset": float(parts[1]),
                "frame_offset": float(parts[2]),
                "note": int(parts[3]),
                "velocity": int(parts[4]),
                "hand": row_hand,
                "finger": FINGERS[finger - 1] if finger and 1 <= finger <= 5 else None,
                "prior_finger": FINGERS[finger - 1] if finger and 1 <= finger <= 5 else None,
            })
    groups = []
    for event in sorted(events, key=lambda item: (item["onset"], item["note"])):
        if groups and abs(groups[-1][0]["onset"] - event["onset"]) < 1e-6:
            groups[-1].append(event)
        else:
            groups.append([event])
    return groups


def evaluate(groups, first, last, prefer_low, prefer_high):
    events = [event for group in groups[first:last + 1] for event in group]
    if not 20 <= len(events) <= 30:
        return None
    if first > 0:
        if max(event["key_offset"] for event in groups[first - 1]) > \
                groups[first][0]["onset"] + 1e-6:
            return None
    if last + 1 < len(groups):
        if groups[last + 1][0]["onset"] < max(
                event["key_offset"] for event in events) - 1e-6:
            return None
    gaps = []
    for index in range(first, last):
        previous_end = max(
            event["key_offset"] for event in groups[index])
        gaps.append({
            "after_group": index,
            "gap_sec": groups[index + 1][0]["onset"] - previous_end,
        })
    hits = [item for item in gaps
            if 0.05 - 1e-6 <= item["gap_sec"] <= 0.15 + 1e-6]
    if len(hits) < 3:
        return None
    notes = [event["note"] for event in events]
    repeated = any(notes.count(note) >= 2 for note in set(notes))
    low = all(prefer_low <= note <= prefer_high for note in notes)
    score = (len(hits) * 10 + (5 if repeated else 0) + (20 if low else 0)
             - abs(len(events) - 25) + len(set(notes)))
    return {
        "first_group": first,
        "last_group": last,
        "events": events,
        "gaps": gaps,
        "gap_hits": len(hits),
        "repeated": repeated,
        "low_range": low,
        "note_min": min(notes),
        "note_max": max(notes),
        "score": score,
        "start": events[0]["onset"],
        "end": max(event["key_offset"] for event in events),
    }


def select(groups, prefer_low, prefer_high):
    best = None
    for first in range(len(groups)):
        for last in range(first, len(groups)):
            result = evaluate(groups, first, last, prefer_low, prefer_high)
            if result is None:
                continue
            if best is None or result["score"] > best["score"]:
                best = result
    return best


def write_window(path, source, window):
    origin = window["start"]
    lines = [
        "format: piano_fingering/1",
        f"source: {source}",
        "events:",
    ]
    for index, event in enumerate(window["events"], start=1):
        start = event["onset"] - origin
        end = event["key_offset"] - origin
        lines.append(
            "  - {id: %d, hand: right, start: %.6f, end: %.6f, "
            "note: %d, velocity: %d, finger: %s}" % (
                index, start, end, event["note"], event["velocity"],
                event["finger"] or "null"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fingering-dir", type=Path,
        default=Path(r"C:\Users\admin\Desktop\doc\code\pianoWAM\data\PianoVAM_v1.2\Fingering_GT"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--validation-output", type=Path, default=None)
    parser.add_argument("--validation-map", type=Path, default=None)
    parser.add_argument("--hand", choices=["right", "left"], default="right")
    parser.add_argument("--prefer-low", type=int, default=60)
    parser.add_argument("--prefer-high", type=int, default=67)
    parser.add_argument("--validation-file", default=None,
                        help="use a different recording for the validation window")
    args = parser.parse_args(argv)
    try:
        candidates = []
        for path in sorted(args.fingering_dir.glob("*.tsv")):
            groups = load_groups(path, args.hand)
            best = select(groups, args.prefer_low, args.prefer_high)
            if best is None:
                continue
            candidates.append((best["score"], path, best, groups))
        if not candidates:
            raise ValueError("no 20-30 note window with three 50-150 ms gaps")
        candidates.sort(key=lambda item: (-item[0], str(item[1])))
        score, path, window, groups = candidates[0]
        origin = window["start"]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_window(args.output, f"{path.name} groups "
                     f"{window['first_group']}-{window['last_group']}",
                     window)
        mapping = {
            "source": str(path),
            "source_sha256": _sha256(path),
            "hand": args.hand,
            "first_group": window["first_group"],
            "last_group": window["last_group"],
            "origin_sec": origin,
            "start_sec": window["start"],
            "end_sec": window["end"],
            "events": len(window["events"]),
            "groups": window["last_group"] - window["first_group"] + 1,
            "note_min": window["note_min"],
            "note_max": window["note_max"],
            "repeated": window["repeated"],
            "low_range": window["low_range"],
            "gap_hits": window["gap_hits"],
            "gaps": window["gaps"],
            "mapping": "plan_time = source_time - origin_sec + start_padding",
        }
        args.map.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
        print("SELECTED", path.name, "events", len(window["events"]),
              "groups", mapping["groups"], "range",
              (window["note_min"], window["note_max"]),
              "gap_hits", window["gap_hits"], "low", window["low_range"],
              "repeated", window["repeated"], "score", score)
        if args.validation_output and args.validation_map:
            validation = None
            for score2, path2, window2, _ in candidates:
                if args.validation_file:
                    if path2.name != args.validation_file:
                        continue
                elif path2 == path:
                    continue
                validation = (path2, window2)
                break
            if validation is None:
                raise ValueError("no validation window from a different recording")
            path2, window2 = validation
            args.validation_output.parent.mkdir(parents=True, exist_ok=True)
            write_window(args.validation_output, f"{path2.name} groups "
                         f"{window2['first_group']}-{window2['last_group']}",
                         window2)
            args.validation_map.write_text(json.dumps({
                "source": str(path2),
                "source_sha256": _sha256(path2),
                "first_group": window2["first_group"],
                "last_group": window2["last_group"],
                "origin_sec": window2["start"],
                "events": len(window2["events"]),
                "gaps": window2["gaps"],
                "gap_hits": window2["gap_hits"],
                "low_range": window2["low_range"],
                "repeated": window2["repeated"],
            }, indent=2), encoding="utf-8")
            print("VALIDATION", path2.name, "events", len(window2["events"]))
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
