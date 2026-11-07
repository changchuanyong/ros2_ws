"""Score timing and recorded event round-trip tests."""

import json
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rm_piano_player.midi_file import export_midi, read_score  # noqa: E402


def test_format_one_applies_tempo_changes_and_running_status(tmp_path):
    tempo = b"\x00\xff\x51\x03\x07\xa1\x20\x83\x60\xff\x51\x03\x0f\x42\x40"
    notes = b"\x00\x90\x4a\x40\x83\x60\x4a\x00\x00\x4a\x40\x83\x60\x4a\x00"
    path = tmp_path / "score.mid"
    data = bytearray(b"MThd" + struct.pack(">IHHH", 6, 1, 2, 480))
    for track in (tempo, notes):
        track += b"\x00\xff\x2f\x00"
        data += b"MTrk" + struct.pack(">I", len(track)) + track
    path.write_bytes(data)
    assert [(note.note, note.start, note.end) for note in read_score(path)] == [
        (74, 0, 0.5), (74, 0.5, 1.5),
    ]


def test_midi_export_round_trip_preserves_channel_and_note_length(tmp_path):
    source = tmp_path / "events.jsonl"
    source.write_text(
        "".join(json.dumps({"event": "midi", "type": edge, "note": 73, "channel": 1,
                            "velocity": velocity, "monotonic_ns": stamp}) + "\n"
                for edge, velocity, stamp in (("on", 91, 7_000_000_000),
                                              ("off", 0, 7_120_000_000))),
        encoding="utf-8",
    )
    path = tmp_path / "recording.mid"
    assert export_midi(source, path) == 2
    note, = read_score(path)
    assert (note.note, note.channel, note.velocity) == (73, 1, 91)
    assert note.start == 0
    assert note.end == pytest.approx(0.12)
