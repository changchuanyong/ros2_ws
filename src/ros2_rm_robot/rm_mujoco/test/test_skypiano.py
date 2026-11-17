"""Data semantics and calibration tests; no robot runtime required."""

import csv
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "scripts"))

from pig_score import read_notes  # noqa: E402

from rm_mujoco.skypiano import (  # noqa: E402
    curriculum_fragments, hand_features, keyboard_frame, note_sequence_bytes,
    note_windows, prepare_sample, read_events,
    read_motion, to_keyboard, transform_targets, verify_split_isolation,
)


def motion_fixture(tmp_path, frames=31):
    markers = [prefix + suffix for prefix in "LR"
               for suffix in ("Wrist", "TF", "IF", "MF", "RF", "LF", "IM", "LM")]
    markers += ["LEnd1", "REnd1", "LEnd", "REnd"]
    points = np.zeros((frames, len(markers), 3))
    for prefix in "LR":
        points[:, markers.index(prefix + "IM")] = [500, 70, 20]
        points[:, markers.index(prefix + "LM")] = [570, 70, 20]
        points[:, markers.index(prefix + "Wrist")] = [535, 150, 30]
    points[:, markers.index("REnd1"), 0] = 1300
    points[:, markers.index("REnd"), 0] = 1300
    points[:, markers.index("LEnd"), 1] = -78
    points[:, markers.index("REnd"), 1] = -78
    path = tmp_path / "motion_hand_raw_flagged.csv"
    write_motion(path, markers, points)
    return markers, points, path


def write_motion(path, markers, points):
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([name + "_" + axis for name in markers for axis in "xyz"])
        writer.writerows(points.reshape(len(points), -1))


def event_fixture(tmp_path, unknown=False):
    path = tmp_path / "fingering_events.csv"
    path.write_text("onset,offset,pitch,hand,finger,finger_name\n"
                    + ("0.2000,0.5000,60,,,RIF\n" if unknown else
                       "0.2000,0.5000,60,R,2,RIF\n"))
    notes = [SimpleNamespace(start=0.20002, end=0.50004, note=60, velocity=87)]
    return path, notes


def test_motion_missing_is_not_origin_and_mm_becomes_m(tmp_path):
    markers, points, path = motion_fixture(tmp_path)
    points[0, 0, 0] = np.nan
    write_motion(path, markers, points)
    names, result = read_motion(path)
    assert names == markers
    assert np.isnan(result[0, 0]).all()
    assert result[1, names.index("REnd1"), 0] == 1.3


@pytest.mark.parametrize("text", [
    "A_x,A_y\n1,2\n3,4\n", "A_x,A_y,A_z\n1,2\n3,4,5\n",
    "A_x,A_y,A_z\n1,2,inf\n3,4,5\n", "A_x,A_y,A_z,A_x\n1,2,3,4\n",
])
def test_bad_motion_rejected(tmp_path, text):
    path = tmp_path / "bad.csv"
    path.write_text(text)
    with pytest.raises(ValueError):
        read_motion(path)


def test_keyboard_right_handed_and_primary_reference_agrees(tmp_path):
    markers, _, path = motion_fixture(tmp_path)
    _, raw = read_motion(path)
    aux = keyboard_frame(markers, raw)
    raw[:, [markers.index("LEnd1"), markers.index("REnd1")]] = np.nan
    primary = keyboard_frame(markers, raw)
    assert np.allclose(aux["origin_capture_m"], primary["origin_capture_m"])
    assert np.isclose(np.linalg.det(aux["capture_from_keyboard_rotation"]), 1)
    assert np.allclose(to_keyboard(np.array(aux["origin_capture_m"]), aux), 0)


def test_keyboard_rejects_unit_error_and_moving_reference(tmp_path):
    markers, points, path = motion_fixture(tmp_path)
    with pytest.raises(ValueError, match="span"):
        keyboard_frame(markers, points)
    _, raw = read_motion(path)
    raw[1, markers.index("LEnd1"), 0] += 0.1
    with pytest.raises(ValueError, match="moves"):
        keyboard_frame(markers, raw)


def test_midi_times_velocity_and_unknown_labels_preserved(tmp_path):
    path, notes = event_fixture(tmp_path, unknown=True)
    score, labels = read_events(path, notes)
    event = score["events"][0]
    assert (event["start"], event["end"], event["velocity"]) == (0.20002, 0.50004, 87)
    assert event["hand"] is None and event["finger"] is None
    assert labels[0]["confidence"] is None


@pytest.mark.parametrize("kind", ["missing", "ambiguous", "wrong_offset"])
def test_midi_fingering_mismatch_fails(tmp_path, kind):
    path, notes = event_fixture(tmp_path)
    if kind == "missing":
        notes = []
    elif kind == "ambiguous":
        path.write_text(path.read_text() + "0.2000,0.5000,60,R,2,RIF\n")
        notes *= 2
    else:
        notes[0].end = 0.7
    with pytest.raises(ValueError):
        read_events(path, notes)


def test_detail_label_conflict_is_rejected(tmp_path):
    path, notes = event_fixture(tmp_path)
    detail = tmp_path / "fingering.json"
    detail.write_text(json.dumps({"fingering": [
        {"pitch": 60, "onset": .2, "offset": .5, "hand": "Right", "finger": 3}]}))
    with pytest.raises(ValueError, match="disagreement"):
        read_events(path, notes, detail)


def test_palm_rotation_and_explicit_world_transform(tmp_path):
    markers, _, path = motion_fixture(tmp_path)
    _, raw = read_motion(path)
    features = hand_features(markers, to_keyboard(raw, keyboard_frame(markers, raw)))
    assert features["right_palm_valid"].all()
    assert np.allclose(np.linalg.det(features["right_palm_rotation"]), 1)
    transform = np.eye(4)
    transform[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
    transform[:3, 3] = [1, 2, 3]
    mapped = transform_targets(features, transform)
    expected = features["right_wrist_m"] @ transform[:3, :3].T + [1, 2, 3]
    assert np.allclose(mapped["right_wrist_m"], expected)


@pytest.mark.parametrize("matrix", [np.eye(3), np.diag([-1, 1, 1, 1]),
                                     np.diag([1000, 1000, 1000, 1])])
def test_nonrigid_calibration_rejected(matrix):
    with pytest.raises(ValueError):
        transform_targets({}, matrix)


def test_windows_keep_held_context_and_missing_markers(tmp_path):
    markers, _, path = motion_fixture(tmp_path)
    _, raw = read_motion(path)
    observed = np.isfinite(raw).all(axis=2)
    observed[10, markers.index("RIF")] = False
    events = [{"id": 1, "hand": "right", "finger": "index", "start": .3, "end": .6},
              {"id": 2, "hand": "right", "finger": "thumb", "start": 0, "end": .4}]
    windows = note_windows(events, [{"id": 1, "confidence": .9}],
                           np.arange(31) / 30, markers, observed)
    assert len(windows) == 1
    assert windows[0]["context_event_ids"] == [2]
    assert not windows[0]["isolated_in_hand"]
    assert 0 < windows[0]["observed_fraction"] < 1
    assert not windows[0]["robot_expert_eligible"]


def test_prepare_preserves_observed_and_marks_imputation(tmp_path):
    markers, points, raw_path = motion_fixture(tmp_path)
    imputed = points.copy()
    points[8, markers.index("RIF")] = np.nan
    write_motion(raw_path, markers, points)
    imputed[9, markers.index("RIF"), 0] += 1
    write_motion(tmp_path / "motion_hand_imputed.csv", markers, imputed)
    _, notes = event_fixture(tmp_path)
    (tmp_path / "midi.mid").write_bytes(b"fixture: notes passed separately")
    _, _, arrays, _, report = prepare_sample(tmp_path, notes, 30, "p1", "scale", "train")
    assert np.isnan(arrays["right_tips_m"][8, 1]).all()
    assert arrays["inferred_filled_mask"][8, markers.index("RIF")]
    assert arrays["changed_observed_mask"][9, markers.index("RIF")]
    assert report["robot_expert_eligible"] is False
    with pytest.raises(ValueError, match="beyond motion"):
        prepare_sample(tmp_path, notes, 120, "p1", "scale", "train")


@pytest.mark.parametrize("field", ["subject", "piece", "sha256"])
def test_corpus_split_leakage_rejected(field):
    first = {"subject": "p1", "piece": "scale", "split": "train",
             "sources": [{"sha256": "aaa"}]}
    second = {"subject": "p2", "piece": "technique", "split": "valid",
              "sources": [{"sha256": "bbb"}]}
    assert verify_split_isolation([first, second])
    if field == "sha256":
        second["sources"] = first["sources"]
    else:
        second[field] = first[field]
    with pytest.raises(ValueError, match="leakage"):
        verify_split_isolation([first, second])


def test_curriculum_keeps_chord_and_rejects_unknown_connected_notes(tmp_path):
    path, notes = event_fixture(tmp_path)
    score, _ = read_events(path, notes)
    first = score["events"][0]
    chord = {**first, "id": 2, "note": 64, "finger": "middle"}
    unknown = {**first, "id": 3, "start": 1.0, "end": 1.5,
               "hand": None, "finger": None}
    held = {**first, "id": 4, "start": 1.3, "end": 1.7}
    fragments = curriculum_fragments([first, chord, unknown, held])
    assert len(fragments) == 1
    assert fragments[0]["source_event_ids"] == [1, 2]
    assert len(fragments[0]["events"]) == 2
    assert curriculum_fragments([first, chord], max_notes=1) == []
    relative = fragments[0]["events"][0]
    assert np.isclose(relative["end"] - relative["start"], first["end"] - first["start"])


def test_note_sequence_roundtrip_and_no_unknown_finger_export(tmp_path):
    path, notes = event_fixture(tmp_path)
    score, _ = read_events(path, notes)
    events = score["events"] + [{**score["events"][0], "id": 2, "hand": "left",
                                  "finger": "little", "note": 48}]
    target = tmp_path / "score.proto"
    target.write_bytes(note_sequence_bytes(events))
    decoded = read_notes(target)
    assert [note["part"] for note in decoded] == [1, 9]
    assert [(n["pitch"], n["start"], n["end"], n["velocity"]) for n in decoded] == [
        (e["note"], e["start"], e["end"], e["velocity"]) for e in events]
    events[1]["finger"] = None
    with pytest.raises(ValueError, match="fully labeled"):
        note_sequence_bytes(events)


def test_unrelated_optional_details_are_not_auto_loaded(tmp_path):
    motion_fixture(tmp_path)
    _, notes = event_fixture(tmp_path)
    (tmp_path / "midi.mid").write_bytes(b"fixture")
    detail = tmp_path / "fingering.json"
    detail.write_text(json.dumps({"fingering": [], "n_frames": 10000, "fps": 120}))
    result = prepare_sample(tmp_path, notes, 30, "p1", "scale", "train")
    assert result[-1]["fingering_details_used"] is None
    assert result[1][0]["confidence"] is None
    with pytest.raises(ValueError, match="detail count"):
        prepare_sample(tmp_path, notes, 30, "p1", "scale", "train", detail)
