"""Check PianoVAM-to-RL task extraction without a performance plan."""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "scripts"))

import import_pianovam  # noqa: E402
import prepare_pianovam_tasks  # noqa: E402
from rm_mujoco.pianovam_corpus import MANIFEST_FORMAT, load_corpus_manifest  # noqa: E402
from rm_mujoco.pianovam_tasks import (  # noqa: E402
    FINGER_HINT_UNKNOWN, NoTaskWindows, build_task_set, extract_tasks, load_task_set,
    task_set_from_dict, task_set_to_dict,
)

HEADER = "onset\tkey_offset\tframe_offset\tnote\tvelocity\thand\tfinger\n"


def _write_tsv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + "".join(
        "\t".join(str(value) for value in row) + "\n" for row in rows),
        encoding="utf-8")
    return path


def _rows(*rows):
    return rows


def _events(rows, hand="all", left_max_note=59):
    fields = ("onset", "key_offset", "frame_offset", "note", "velocity", "hand", "finger")
    documents = []
    for row in rows:
        document = dict(zip(fields, row))
        document["finger"] = str(document["finger"])
        documents.append(document)
    return import_pianovam.to_events(
        import_pianovam.validate_rows(documents, "<fixture>"),
        hand_filter=hand, left_max_note=left_max_note)


def test_single_note_keeps_absolute_times_and_targets():
    events = _events(_rows((1.0, 1.5, 3.0, 60, 80, "R", 1)))
    task_set = build_task_set(events, source="song.tsv", split="train",
                              source_sha256="a" * 64, max_tasks=1)
    task = task_set.tasks[0]
    event = task.events[0]
    assert event.start_sec == pytest.approx(1.0)
    assert event.end_sec == pytest.approx(1.5)
    assert task.origin_sec == pytest.approx(1.0)
    assert task.duration_sec == pytest.approx(1.1)
    assert event.finger == "thumb"
    assert event.finger_source == "labeled"
    assert event.hand_source == "labeled"
    # Frame at 0.2 s is inside the note; frame at 0.6 s is in the tail.
    index = int(np.argmin(np.abs(task.frame_time_sec - 0.2)))
    assert task.target_keys[index, 60 - 21] == 1
    assert task.finger_hints[index, 5] == 0
    tail_index = int(np.argmin(np.abs(task.frame_time_sec - 0.6)))
    assert task.target_keys[tail_index, 60 - 21] == 0


def test_noinfo_finger_and_hand_are_marked_not_invented():
    events = _events(_rows((1.0, 1.5, 2.0, 48, 70, "Noinfo", "Noinfo")))
    task = build_task_set(events, source="song.tsv", split="train",
                          source_sha256="a" * 64).tasks[0]
    event = task.events[0]
    assert event.hand == "left"
    assert event.hand_source == "inferred"
    assert event.finger is None
    assert event.finger_source == "unlabeled"
    index = int(np.argmin(np.abs(task.frame_time_sec - 0.2)))
    assert task.finger_hints[index, 0:5].tolist() == [FINGER_HINT_UNKNOWN] * 5


def test_chord_at_one_onset_is_one_window():
    events = _events(_rows(
        (1.0, 1.5, 3.0, 60, 80, "R", 1),
        (1.0, 1.5, 3.0, 64, 75, "R", 3)))
    task = build_task_set(events, source="song.tsv", split="train",
                          source_sha256="a" * 64, window_notes=1).tasks[0]
    assert len(task.events) == 2
    assert {event.note for event in task.events} == {60, 64}
    index = int(np.argmin(np.abs(task.frame_time_sec - 0.2)))
    assert task.target_keys[index, 60 - 21] == 1
    assert task.target_keys[index, 64 - 21] == 1


def test_lead_in_preserves_event_time_and_adds_preparation():
    events = _events(_rows((1.0, 1.5, 3.0, 60, 80, "R", 1)))
    task = build_task_set(events, source="song.tsv", split="train",
                          source_sha256="a" * 64, lead_in_sec=0.2).tasks[0]
    assert task.origin_sec == pytest.approx(0.8)
    assert task.events[0].start_sec == pytest.approx(1.0)
    assert task.duration_sec == pytest.approx(1.3)
    index = int(np.argmin(np.abs(task.frame_time_sec - 0.2)))
    assert task.target_keys[index, 60 - 21] == 1


def test_carry_in_is_rejected_by_default_and_explicitly_possible():
    events = _events(_rows(
        (0.0, 1.0, 3.0, 60, 80, "R", 1),
        (0.5, 1.2, 3.0, 64, 75, "R", 3)))
    default = extract_tasks(events, source="song.tsv", split="train",
                            window_notes=1, allow_carry_in=False)
    assert len(default) == 1
    allowed = extract_tasks(events, source="song.tsv", split="train",
                            window_notes=1, allow_carry_in=True)
    assert len(allowed) == 2
    assert any(event.start_sec < task.origin_sec
               for task in allowed for event in task.events)


def test_complete_phrase_preserves_staggered_overlaps_on_both_boundaries():
    events = _events(_rows(
        (0.90, 1.15, 3.0, 53, 80, "L", 1),
        (1.00, 1.30, 3.0, 54, 80, "L", 2),
        (1.10, 1.40, 3.0, 55, 80, "L", 3)))
    with pytest.raises(NoTaskWindows):
        extract_tasks(events, source="song.tsv", split="train",
                      window_notes=1, lead_in_sec=0.2, complete_phrases=True)
    task, = extract_tasks(events, source="song.tsv", split="train",
                          window_notes=3, lead_in_sec=0.2, complete_phrases=True)
    assert [(event.start_sec, event.end_sec) for event in task.events] == [
        (0.90, 1.15), (1.00, 1.30), (1.10, 1.40)]
    isolated = extract_tasks(events, source="song.tsv", split="train",
                             window_notes=1, lead_in_sec=0.2)
    assert [event.note for task in isolated for event in task.events] == [53]


def test_complete_phrase_only_uses_silent_lead_in():
    events = _events(_rows(
        (0.90, 0.95, 3.0, 53, 80, "L", 1),
        (1.00, 1.30, 3.0, 54, 80, "L", 2)))
    _, second = extract_tasks(events, source="song.tsv", split="train",
                              window_notes=1, lead_in_sec=0.2, complete_phrases=True)
    assert second.origin_sec == 0.95
    assert [event.start_sec for event in second.events] == [1.0]


def test_task_loader_rejects_tampered_targets():
    events = _events(_rows((1.0, 1.5, 3.0, 60, 80, "R", 1)))
    task_set = build_task_set(events, source="song.tsv", split="train",
                              source_sha256="a" * 64)
    document = task_set_to_dict(task_set)
    document["tasks"][0]["frames"]["target_keys"][0][0] = 1
    with pytest.raises(ValueError, match="target_keys"):
        task_set_from_dict(document)


def test_split_is_preserved_in_task_file(tmp_path):
    source = _write_tsv(tmp_path / "dataset/Fingering_GT/song.tsv",
                        _rows((1.0, 1.5, 3.0, 60, 80, "R", 1)))
    (tmp_path / "dataset/metadata.json").write_text(json.dumps({
        "song": {"record_time": "song", "split": "ext-train",
                 "composer": "Composer", "piece": "Song"}}), encoding="utf-8")
    output = tmp_path / "tasks"
    assert prepare_pianovam_tasks.main([
        "--dataset", str(tmp_path / "dataset"), "--output", str(output),
    ]) == 0
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["format"] == MANIFEST_FORMAT
    assert "ext-train" in manifest["splits"]
    task_path = output / "ext-train/song.tasks.json"
    task_set = load_task_set(task_path)
    assert task_set.split == "ext-train"
    assert task_set.source_sha256 == hashlib.sha256(
        source.read_bytes()).hexdigest()
    phases = load_corpus_manifest(output / "manifest.json")
    assert phases["train"].recordings[0].piece == "Song"
    task_path.write_text(task_path.read_text() + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="task checksum"):
        load_corpus_manifest(output / "manifest.json")


def test_dataset_refuses_same_piece_in_two_phases(tmp_path):
    dataset = tmp_path / "dataset"
    metadata = {}
    for index, (split, piece) in enumerate((("train", "My Song"), ("valid", "my   song"))):
        name = f"recording-{index}"
        metadata[name] = {"record_time": name, "split": split, "composer": "Composer",
                          "piece": piece}
        _write_tsv(dataset / "Fingering_GT" / f"{name}.tsv",
                   [(1.0, 1.5, 2.0, 60 + index, 80, "R", 1)])
    (dataset / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    output = tmp_path / "tasks"
    assert prepare_pianovam_tasks.main([
        "--dataset", str(dataset), "--output", str(output),
    ]) == 2
    assert not (output / "manifest.json").exists()


def test_cli_task_file_has_no_performance_plan(tmp_path):
    source = _write_tsv(tmp_path / "song.tsv",
                        _rows((1.0, 1.5, 3.0, 60, 80, "R", 1)))
    output = tmp_path / "song.tasks.json"
    assert prepare_pianovam_tasks.main([
        "--fingering", str(source), "--split", "train", "--output", str(output),
    ]) == 0
    document = json.loads(output.read_text())
    assert document["format"] == "piano_rl_tasks/1"
    text = output.read_text()
    for forbidden in ("piano_performance", "arm_waypoints", "hand_states",
                      "plan_performance", "PlanRunner"):
        assert forbidden not in text
