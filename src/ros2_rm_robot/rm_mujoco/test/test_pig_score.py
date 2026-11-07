"""Check the PIG proto to flat-palm score conversion."""

import struct
from pathlib import Path
import sys

import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "scripts"))
sys.path.insert(0, str(PACKAGE.parent / "rm_piano_player"))

import pig_score  # noqa: E402
from rm_piano_player.midi_file import read_score  # noqa: E402


def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _varint_field(number, value):
    return _varint(number << 3) + _varint(value)


def _double_field(number, value):
    return _varint((number << 3) | 1) + struct.pack("<d", value)


def _bytes_field(number, value):
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _note(pitch, start, end, part, velocity=80):
    body = (_varint_field(1, pitch) + _varint_field(2, velocity)
            + _double_field(3, start) + _double_field(4, end)
            + _varint_field(10, part & 0xFFFFFFFFFFFFFFFF))
    return _bytes_field(8, body)


def _write(tmp_path, name, notes):
    path = tmp_path / f"{name}.proto"
    path.write_bytes(b"".join(_note(*note) for note in notes))
    return path


def _simple_score():
    # Right hand walks up the C major triad; left hand holds its own range.
    return [
        (72, 0.0, 0.5, 0), (76, 0.5, 1.0, 2), (79, 1.0, 1.5, 4),
        (48, 0.0, 0.5, 5), (52, 0.5, 1.0, 7), (55, 1.0, 1.5, 9),
    ]


def test_notes_are_read_from_the_wire_format(tmp_path):
    path = _write(tmp_path, "simple", _simple_score())
    notes = pig_score.read_notes(path)
    assert len(notes) == 6
    first = notes[0]
    assert (first["pitch"], first["part"]) == (72, 0)
    assert first["start"] == pytest.approx(0.0)
    assert first["end"] == pytest.approx(0.5)


def test_conversion_round_trips_through_the_score_reader(tmp_path):
    path = _write(tmp_path, "simple", _simple_score())
    hands = pig_score.split_hands(pig_score.read_notes(path))
    table, conflicts = pig_score.fingering_table(hands)
    assert not conflicts
    assert table["right"] == {72: ["C", "thumb"], 76: ["E", "middle"], 79: ["G", "little"]}
    assert table["left"] == {48: ["C", "thumb"], 52: ["E", "middle"], 55: ["G", "little"]}

    midi = tmp_path / "simple.mid"
    pig_score.write_midi(hands, midi)
    score = read_score(midi)
    assert [(note.channel, note.note) for note in score] == [
        (0, 72), (1, 48), (0, 76), (1, 52), (0, 79), (1, 55)]
    assert all(note.start < note.end for note in score)

    written = tmp_path / "simple.yaml"
    written.write_text(yaml.safe_dump(table, sort_keys=True), encoding="utf-8")
    assert yaml.safe_load(written.read_text()) == table


def test_overlapping_notes_are_rejected(tmp_path):
    path = _write(tmp_path, "overlap", [
        (72, 0.0, 1.0, 0), (74, 0.5, 1.5, 1),
        (48, 0.0, 0.5, 5)])
    with pytest.raises(ValueError, match="overlapping"):
        pig_score.split_hands(pig_score.read_notes(path))


def test_one_handed_scores_are_rejected(tmp_path):
    path = _write(tmp_path, "right_only", [(72, 0.0, 0.5, 0), (74, 0.5, 1.0, 1)])
    with pytest.raises(ValueError, match="no left-hand"):
        pig_score.split_hands(pig_score.read_notes(path))


def test_missing_fingering_is_rejected(tmp_path):
    path = _write(tmp_path, "no_finger", [(72, 0.0, 0.5, -1), (48, 0.0, 0.5, 5)])
    with pytest.raises(ValueError, match="expected 0-9"):
        pig_score.split_hands(pig_score.read_notes(path))


def test_repeated_pitch_with_two_fingers_needs_a_policy(tmp_path):
    # A scale turns the thumb under, so the same pitch is fingered twice.
    path = _write(tmp_path, "turn", [
        (72, 0.0, 0.5, 0), (74, 0.5, 1.0, 1), (72, 1.0, 1.5, 2),
        (48, 0.0, 0.5, 5)])
    hands = pig_score.split_hands(pig_score.read_notes(path))
    with pytest.raises(ValueError, match="single pose per hand"):
        pig_score.fingering_table(hands)
    first, conflicts = pig_score.fingering_table(hands, "first")
    assert first["right"][72] == ["C", "thumb"]
    assert conflicts
    common, _ = pig_score.fingering_table(hands, "most-common")
    assert common["right"][72] == ["C", "thumb"]
