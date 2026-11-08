"""Check the PianoVAM TSV to per-note event conversion."""

from pathlib import Path
import sys

import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "scripts"))

import import_pianovam  # noqa: E402

HEADER = "onset\tkey_offset\tframe_offset\tnote\tvelocity\thand\tfinger\n"


def _write(tmp_path, rows, name="fingering.tsv"):
    path = tmp_path / name
    path.write_text(HEADER + "".join("\t".join(map(str, row)) + "\n" for row in rows),
                    encoding="utf-8")
    return path


def _row(onset, key_offset, frame_offset, note, velocity, hand, finger):
    return (onset, key_offset, frame_offset, note, velocity, hand, finger)


def test_end_uses_key_offset_not_pedal_frame_offset(tmp_path):
    path = _write(tmp_path, [
        _row(1.0, 1.25, 3.5, 60, 80, "R", 1),
        _row(1.0, 1.5, 4.0, 64, 75, "R", 3),
    ])
    rows = import_pianovam.validate_rows(import_pianovam.read_fingering(path), path)
    events = import_pianovam.to_events(rows, hand_filter="right")
    assert [(event["note"], event["start"], event["end"]) for event in events] == [
        (60, 1.0, 1.25), (64, 1.0, 1.5)]


def test_noinfo_becomes_a_null_finger_and_keeps_the_event(tmp_path):
    path = _write(tmp_path, [
        _row(1.0, 1.2, 2.0, 60, 80, "Noinfo", "Noinfo"),
        _row(1.0, 1.3, 2.0, 48, 70, "L", 5),
    ])
    rows = import_pianovam.validate_rows(import_pianovam.read_fingering(path), path)
    events = import_pianovam.to_events(rows)
    unknown = next(event for event in events if event["note"] == 60)
    assert unknown["hand"] is None
    assert unknown["finger"] is None
    assert next(event for event in events if event["note"] == 48)["hand"] == "left"


def test_chord_and_limit(tmp_path):
    path = _write(tmp_path, [
        _row(1.0, 1.5, 3.0, 60, 80, "R", 1),
        _row(1.0, 1.5, 3.0, 64, 75, "R", 3),
        _row(2.0, 2.5, 3.0, 67, 70, "R", 5),
    ])
    rows = import_pianovam.validate_rows(import_pianovam.read_fingering(path), path)
    events = import_pianovam.to_events(rows, hand_filter="right", limit=2)
    assert [event["note"] for event in events] == [60, 64]


def test_more_than_five_simultaneous_notes_are_rejected(tmp_path):
    path = _write(tmp_path, [
        _row(1.0, 1.5, 3.0, note, 80, "R", (index % 5) + 1)
        for index, note in enumerate((60, 62, 64, 65, 67, 69))
    ])
    rows = import_pianovam.validate_rows(import_pianovam.read_fingering(path), path)
    with pytest.raises(ValueError, match="five fingers"):
        import_pianovam.to_events(rows, hand_filter="right")


def test_bad_key_offset_is_rejected(tmp_path):
    path = _write(tmp_path, [_row(1.0, 1.0, 3.0, 60, 80, "R", 1)])
    rows = import_pianovam.read_fingering(path)
    with pytest.raises(ValueError, match="key_offset"):
        import_pianovam.validate_rows(rows, path)


def test_hand_filter_uses_pitch_for_noinfo_rows(tmp_path):
    path = _write(tmp_path, [
        _row(1.0, 1.5, 2.0, 48, 60, "Noinfo", "Noinfo"),
        _row(1.0, 1.5, 2.0, 72, 80, "Noinfo", "Noinfo"),
        _row(1.0, 1.5, 2.0, 50, 60, "L", 5),
        _row(1.0, 1.5, 2.0, 74, 80, "R", 2),
    ])
    rows = import_pianovam.validate_rows(import_pianovam.read_fingering(path), path)
    right = import_pianovam.to_events(rows, hand_filter="right", left_max_note=59)
    assert [event["note"] for event in right] == [72, 74]
    left = import_pianovam.to_events(rows, hand_filter="left", left_max_note=59)
    assert [event["note"] for event in left] == [48, 50]


def test_write_events_round_trips_the_schema(tmp_path):
    path = _write(tmp_path, [_row(1.0, 1.2, 2.0, 60, 80, "R", 1)])
    rows = import_pianovam.validate_rows(import_pianovam.read_fingering(path), path)
    events = import_pianovam.to_events(rows)
    output = tmp_path / "song.fingering.yaml"
    import_pianovam.write_events(output, events, path)
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert document["format"] == "piano_fingering/1"
    assert document["events"][0]["end"] == pytest.approx(1.2)
    assert document["events"][0]["finger"] == "thumb"
