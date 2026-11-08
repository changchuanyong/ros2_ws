#!/usr/bin/env python3
"""Convert a PianoVAM Fingering TSV into the per-note event format.

The Fingering and Fingering_GT files have seven tab-separated columns:

    onset, key_offset, frame_offset, note, velocity, hand, finger

`key_offset` is when the finger physically leaves the key.  `frame_offset`
includes pedal sustain and must not be used as the note end.  The output is
the canonical `piano_fingering/1` YAML consumed by `plan_performance.py`.

Usage:
    python3 import_pianovam.py --fingering Fingering/2024-09-04_17-02-04.tsv \
        --output song.fingering.yaml --hand right --limit 30
"""

import argparse
import csv
import io
import math
from collections import Counter
from pathlib import Path
import sys

import yaml

FINGER_NAMES = {
    1: "thumb",
    2: "index",
    3: "middle",
    4: "ring",
    5: "little",
}
HAND_NAMES = {"L": "left", "R": "right", "Noinfo": None}
REQUIRED_COLUMNS = (
    "onset", "key_offset", "frame_offset", "note", "velocity", "hand", "finger")


def _number(value, name, row):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric on row {row}: {value!r}") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite on row {row}")
    return number


def _integer(value, name, row):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer on row {row}: {value!r}") from None
    return number


def read_fingering(path):
    """Read a PianoVAM TSV, preserving the labeled hand and finger strings."""
    text = Path(path).read_text(encoding="utf-8-sig")
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise ValueError(f"{path}: fingering file is empty")
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter="\t")
    missing = [name for name in REQUIRED_COLUMNS if name not in (reader.fieldnames or ())]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    rows = []
    for index, row in enumerate(reader, start=2):
        rows.append({
            "onset": _number(row["onset"], "onset", index),
            "key_offset": _number(row["key_offset"], "key_offset", index),
            "frame_offset": _number(row["frame_offset"], "frame_offset", index),
            "note": _integer(row["note"], "note", index),
            "velocity": _integer(row["velocity"], "velocity", index),
            "hand": (row["hand"] or "").strip(),
            "finger": (row["finger"] or "").strip(),
        })
    if not rows:
        raise ValueError(f"{path}: no note rows")
    return rows


def validate_rows(rows, path="<memory>"):
    """Reject rows that cannot become a note event before any planning."""
    seen = set()
    for index, row in enumerate(rows, start=2):
        if row["key_offset"] <= row["onset"]:
            raise ValueError(
                f"{path}: row {index} has key_offset {row['key_offset']} <= onset {row['onset']}")
        if row["onset"] < 0:
            raise ValueError(f"{path}: row {index} has a negative onset")
        if not 21 <= row["note"] <= 108:
            raise ValueError(f"{path}: row {index} note {row['note']} is outside 21-108")
        if not 0 <= row["velocity"] <= 127:
            raise ValueError(f"{path}: row {index} velocity {row['velocity']} is outside 0-127")
        if row["hand"] not in HAND_NAMES:
            raise ValueError(f"{path}: row {index} hand must be L, R or Noinfo")
        if row["finger"] not in ("1", "2", "3", "4", "5", "Noinfo"):
            raise ValueError(f"{path}: row {index} finger must be 1-5 or Noinfo")
        if (row["hand"] == "Noinfo") != (row["finger"] == "Noinfo"):
            raise ValueError(
                f"{path}: row {index} has inconsistent hand/finger {row['hand']}/{row['finger']}")
        key = (row["hand"], row["note"], row["onset"])
        if key in seen:
            raise ValueError(f"{path}: row {index} duplicates hand/note/onset {key}")
        seen.add(key)
    return rows


def _pitch_hand(note, left_max_note):
    return "left" if note <= left_max_note else "right"


def _check_max_simultaneous(events, left_max_note):
    """Reject more than five held notes on one hand; L20 has five fingers."""
    for side in ("left", "right"):
        spans = []
        for event in events:
            hand = event["hand"] or _pitch_hand(event["note"], left_max_note)
            if hand != side:
                continue
            spans.append((event["start"], 1, event["note"], event["id"]))
            spans.append((event["end"], -1, event["note"], event["id"]))
        spans.sort(key=lambda item: (item[0], item[1]))
        active = {}
        for time, delta, note, event_id in spans:
            if delta > 0:
                active[event_id] = (note, time)
                if len(active) > 5:
                    details = sorted(active.values())
                    raise ValueError(
                        f"{side} hand has {len(active)} simultaneous notes at {time:.6f}s: "
                        f"{details}; L20 has five fingers. Use a different excerpt or recording.")
            else:
                active.pop(event_id, None)
    return None


def to_events(rows, hand_filter="all", left_max_note=59, limit=0):
    """Convert validated rows into note events, optionally keeping one hand."""
    if hand_filter not in ("all", "left", "right"):
        raise ValueError("hand_filter must be all, left or right")
    if not 0 <= left_max_note <= 108:
        raise ValueError("left_max_note must be within 0-108")
    events = []
    for row in rows:
        hand = HAND_NAMES[row["hand"]]
        if hand_filter != "all":
            pitch_hand = _pitch_hand(row["note"], left_max_note)
            selected = hand if hand is not None else pitch_hand
            if selected != hand_filter:
                continue
        finger = FINGER_NAMES.get(int(row["finger"])) if row["finger"] != "Noinfo" else None
        events.append({
            "hand": hand if hand_filter == "all" else hand_filter,
            "start": row["onset"],
            "end": row["key_offset"],
            "note": row["note"],
            "velocity": row["velocity"],
            "finger": finger,
        })
    events.sort(key=lambda item: (item["start"], item["hand"] or "", item["note"]))
    if limit:
        if limit <= 0:
            raise ValueError("limit must be positive or zero")
        events = events[:limit]
    if not events:
        raise ValueError("no notes remain after the hand filter")
    for index, event in enumerate(events, start=1):
        event["id"] = index
    ordered = [
        {"id": event["id"], "hand": event["hand"], "start": event["start"],
         "end": event["end"], "note": event["note"], "velocity": event["velocity"],
         "finger": event["finger"]}
        for event in events
    ]
    _check_max_simultaneous(ordered, left_max_note)
    return ordered


def write_events(path, events, source):
    document = {
        "format": "piano_fingering/1",
        "source": str(source),
        "events": events,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return document


def summarize(events):
    hands = Counter(event["hand"] or "Noinfo" for event in events)
    no_finger = sum(1 for event in events if event["finger"] is None)
    return {"events": len(events), "hands": dict(hands), "no_finger": no_finger}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fingering", type=Path, required=True,
                        help="PianoVAM Fingering/*.tsv or Fingering_GT/*.tsv")
    parser.add_argument("--output", type=Path, required=True,
                        help="output song.fingering.yaml")
    parser.add_argument("--hand", choices=("all", "left", "right"), default="all",
                        help="keep only one hand; Noinfo rows use the pitch split")
    parser.add_argument("--left-max-note", type=int, default=59,
                        help="highest MIDI note assigned to the left hand for Noinfo rows")
    parser.add_argument("--limit", type=int, default=0,
                        help="keep the first N notes after filtering (0 means all)")
    args = parser.parse_args(argv)
    try:
        rows = validate_rows(read_fingering(args.fingering), args.fingering)
        events = to_events(rows, args.hand, args.left_max_note, args.limit)
        write_events(args.output, events, args.fingering)
    except (OSError, ValueError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    print(
        f"WROTE {args.output} {summarize(events)}; "
        f"end=key_offset (frame_offset ignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
