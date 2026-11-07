"""Convert a PIG (Piano Fingering Dataset) NoteSequence proto into a flat-palm score.

The PIG release from RoboPianist stores each piece as a serialized magenta
NoteSequence protobuf. Only five fields are needed to build a score for
`run_flat_palms.py`, so this script parses the wire format directly instead of
depending on protobuf or TensorFlow.

Field numbers come from magenta/note-seq `note_seq/protobuf/music.proto`:
NoteSequence.notes = 8, and Note { pitch = 1, velocity = 2, start_time = 3,
end_time = 4, part = 10 }. Fingerings are 0-4 for the right hand and 5-9 for the
left hand, both thumb to pinky; -1 means the note has no fingering.

Usage:
    python3 pig_score.py song.proto OUT_DIR [--name NAME]

Writes NAME.mid (channel 0 right, channel 1 left) and NAME.yaml under OUT_DIR.
"""

import argparse
import struct
import sys
from collections import defaultdict
from pathlib import Path

import yaml

FINGER_NAMES = ("C", "D", "E", "F", "G")
FINGER_PARTS = dict(zip(FINGER_NAMES, ("thumb", "index", "middle", "ring", "little")))
TICKS_PER_SECOND = 960          # 480 PPQN at 120 qpm, so one second is two beats.
RIGHT_CHANNEL, LEFT_CHANNEL = 0, 1


def _read_varint(data, position):
    result = shift = 0
    while True:
        byte = data[position]
        position += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, position
        shift += 7
        if shift > 63:
            raise ValueError("protobuf varint is longer than 10 bytes")


def _read_fields(data):
    """Yield (field_number, wire_type, value) for one serialized message."""
    position = 0
    while position < len(data):
        tag, position = _read_varint(data, position)
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ValueError("protobuf field number 0 is invalid")
        if wire == 0:
            value, position = _read_varint(data, position)
        elif wire == 1:
            value = data[position:position + 8]
            position += 8
        elif wire == 2:
            size, position = _read_varint(data, position)
            value = data[position:position + size]
            position += size
        elif wire == 5:
            value = data[position:position + 4]
            position += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        if position > len(data):
            raise ValueError("truncated protobuf message")
        yield number, wire, value


def _signed32(value):
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def read_notes(path):
    """Read every NoteSequence.Note as a dict of pitch, velocity, start, end, part."""
    notes = []
    for number, wire, value in _read_fields(Path(path).read_bytes()):
        if number != 8 or wire != 2:
            continue
        fields = {}
        for field, wire_type, payload in _read_fields(value):
            if wire_type == 0:
                fields[field] = payload
            elif wire_type == 1:
                fields[field] = payload
        for required in (1, 3, 4):
            if required not in fields:
                raise ValueError(f"note is missing field {required}")
        notes.append({
            "pitch": fields[1],
            "velocity": fields.get(2, 80),
            "start": struct.unpack("<d", bytes(fields[3]))[0],
            "end": struct.unpack("<d", bytes(fields[4]))[0],
            "part": _signed32(fields.get(10, 0)),
        })
    if not notes:
        raise ValueError("no notes found; is this a serialized NoteSequence?")
    return notes


def split_hands(notes):
    """Group notes by hand and reject scores the flat-palm demo cannot play."""
    hands = {"right": [], "left": []}
    for note in notes:
        part = note["part"]
        if not 0 <= part <= 9:
            raise ValueError(
                f"MIDI note {note['pitch']} has part {part}; expected 0-9 (0-4 right, "
                "5-9 left)")
        hands["right" if part < 5 else "left"].append(note)
    for side, hand_notes in hands.items():
        if not hand_notes:
            raise ValueError(f"the score has no {side}-hand notes")
        hand_notes.sort(key=lambda item: (item["start"], item["pitch"]))
        for first, second in zip(hand_notes, hand_notes[1:]):
            if first["end"] > second["start"] + 1e-9:
                raise ValueError(
                    f"the {side} hand has overlapping notes {first['pitch']} and "
                    f"{second['pitch']}; the flat-palm demo plays one note per hand")
    right = {note["pitch"] for note in hands["right"]}
    left = {note["pitch"] for note in hands["left"]}
    if right & left:
        raise ValueError(
            f"both hands use pitches {sorted(right & left)}; the demo needs "
            "distinct hand ranges")
    return hands


def fingering_table(hands, on_conflict="error"):
    """Map each pitch to the PRESS pose and finger named by its part field.

    A pitch played with different fingers in different places cannot be expressed
    by a pitch-to-pose table. `on_conflict` decides what happens then: "error"
    refuses the score, "first" keeps the finger used at the earliest onset, and
    "most-common" keeps the most frequent one.
    """
    table, conflicts = {}, []
    for side, hand_notes in hands.items():
        tally = defaultdict(lambda: defaultdict(int))
        earliest = {}
        for note in sorted(hand_notes, key=lambda item: (item["start"], item["pitch"])):
            letter = FINGER_NAMES[note["part"] % 5]
            tally[note["pitch"]][letter] += 1
            earliest.setdefault(note["pitch"], letter)
        chosen = {}
        for pitch, counts in sorted(tally.items()):
            if len(counts) == 1:
                chosen[pitch] = next(iter(counts))
                continue
            conflicts.append(f"{side} note {pitch}: {dict(sorted(counts.items()))}")
            if on_conflict == "first":
                chosen[pitch] = earliest[pitch]
            elif on_conflict == "most-common":
                best = max(counts.values())
                tied = [letter for letter, count in counts.items() if count == best]
                chosen[pitch] = earliest[pitch] if earliest[pitch] in tied else min(tied)
        table[side] = {
            pitch: [letter, FINGER_PARTS[letter]] for pitch, letter in sorted(chosen.items())
        }
    if conflicts and on_conflict == "error":
        raise ValueError(
            "one pitch needs different poses in different places, but fingering.yaml "
            "maps pitch to a single pose per hand; rerun with --on-conflict first or "
            "--on-conflict most-common: " + "; ".join(conflicts))
    return table, conflicts


def _variable_length(value):
    result = [value & 0x7F]
    while value > 0x7F:
        value >>= 7
        result.insert(0, (value & 0x7F) | 0x80)
    return bytes(result)


def write_midi(hands, path):
    """Write a format-0 MIDI file with channel 0 for the right hand and 1 for the left."""
    events = []
    for side, channel in (("right", RIGHT_CHANNEL), ("left", LEFT_CHANNEL)):
        for note in hands[side]:
            on = round(note["start"] * TICKS_PER_SECOND)
            off = max(round(note["end"] * TICKS_PER_SECOND), on + 1)
            events.append((on, 1, channel, note["pitch"], note["velocity"]))
            events.append((off, 0, channel, note["pitch"], 0))
    events.sort(key=lambda item: (item[0], item[1]))

    track = bytearray(b"\x00\xff\x51\x03\x07\xa1\x20")  # 500000 us per quarter note.
    previous = 0
    for tick, kind, channel, pitch, velocity in events:
        track += _variable_length(tick - previous)
        message = ((0x90 if kind else 0x80) | channel, pitch, velocity)
        track += bytes(message)
        previous = tick
    track += b"\x00\xff\x2f\x00"

    path = Path(path)
    path.write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
                     + b"MTrk" + struct.pack(">I", len(track)) + bytes(track))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("proto", type=Path, help="PIG NoteSequence .proto file")
    parser.add_argument("output", type=Path, help="directory for the .mid and .yaml")
    parser.add_argument("--name", help="base name for the outputs (default: proto stem)")
    parser.add_argument("--on-conflict", choices=("error", "first", "most-common"),
                        default="error",
                        help="what to do when one pitch is fingered differently")
    parser.add_argument("--note-gap", type=float, default=0.0, metavar="SECONDS",
                        help="shorten each note by this much score time so the wrist "
                             "can move between notes; legato scores need about 0.07s")
    args = parser.parse_args()

    notes = read_notes(args.proto)
    if args.note_gap < 0:
        parser.error("--note-gap must not be negative")
    for note in notes:
        note["end"] = max(note["start"] + 0.05, note["end"] - args.note_gap)
    hands = split_hands(notes)
    table, conflicts = fingering_table(hands, args.on_conflict)

    args.output.mkdir(parents=True, exist_ok=True)
    name = args.name or args.proto.stem
    write_midi(hands, args.output / f"{name}.mid")
    (args.output / f"{name}.yaml").write_text(
        yaml.safe_dump(table, sort_keys=True, allow_unicode=True), encoding="utf-8")

    print(f"WROTE {args.output / (name + '.mid')} {args.output / (name + '.yaml')}")
    for side in ("right", "left"):
        pitches = [note["pitch"] for note in hands[side]]
        print(f"{side} {len(hands[side])} notes, pitch {min(pitches)}-{max(pitches)}, "
              f"duration {max(note['end'] for note in hands[side]):.2f}s")
    for conflict in conflicts:
        print(f"CONFLICT {conflict} -> {args.on_conflict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
