"""Regression tests for score adapters, raw event matching and staged CLI failures."""

import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE.parent / "rm_mujoco"))

from rm_piano_player.performance_evaluation import evaluate_events, expected_from_plan  # noqa: E402
from rm_piano_player.performance_pipeline import main  # noqa: E402
from rm_piano_player.score_io import load_score  # noqa: E402


def event(index=1, note=67, start=1.0, end=1.4):
    return {"id": index, "note": note, "start": start, "end": end,
            "hand": "right", "finger": "little", "velocity": 74}


def evaluate(expected, edges, **kwargs):
    return evaluate_events(expected, edges, source="synthetic", **kwargs)


def test_repeated_note_matches_the_later_target_without_hiding_a_missing_note():
    result = evaluate([event(), event(2, start=2.0, end=2.4)],
                      [[2.01, "on", 67], [2.41, "off", 67]])
    assert [item["id"] for item in result["missing"]] == [1]
    assert result["matched"][0]["id"] == 2
    assert result["counts"]["correct"] == 1
    assert not result["passed"]


def test_far_late_note_does_not_match_across_a_rest():
    result = evaluate([event()], [[1.5, "on", 67], [1.9, "off", 67]])
    assert result["counts"]["missing"] == result["counts"]["extra"] == 1
    assert result["counts"]["matched"] == 0


def test_ordered_matching_maximizes_count_in_overlapping_windows():
    result = evaluate([event(end=1.1), event(2, start=1.2, end=1.3)],
                      [[1.11, "on", 67], [1.15, "off", 67],
                       [1.3, "on", 67], [1.4, "off", 67]])
    assert result["counts"]["matched"] == 2
    assert result["counts"]["correct"] == 0


def test_wrong_pitch_remains_missing_plus_extra():
    result = evaluate([event()], [[1.0, "on", 66], [1.4, "off", 66]])
    assert result["missing"][0]["note"] == 67
    assert result["extra"][0]["note"] == 66
    assert result["f1"] == 0


def test_open_note_is_counted_and_release_error_is_unknown():
    result = evaluate([event()], [[1.0, "on", 67]])
    assert result["counts"]["observed"] == 1
    assert result["active_keys_at_end"] == [67]
    assert result["matched"][0]["reasons"] == ["unreleased"]
    assert result["max_release_error_sec"] is None
    assert not result["passed"]


def test_chord_and_independent_releases_are_scored():
    result = evaluate([event(), event(2, note=64, end=1.6)],
                      [[1.0, "on", 67], [1.0, "on", 64],
                       [1.4, "off", 67], [1.6, "off", 64]])
    assert result["passed"] and result["f1"] == 1.0


def test_late_onset_and_release_report_signed_errors():
    result = evaluate([event()], [[1.1, "on", 67], [1.5, "off", 67]])
    assert result["matched"][0]["reasons"] == ["onset_timing", "release_timing"]
    assert result["max_onset_error_sec"] == pytest.approx(0.1)


@pytest.mark.parametrize("edges", [
    [[1.0, "on", 67], [1.01, "on", 67], [1.4, "off", 67]],
    [[0.5, "off", 67], [1.0, "on", 67], [1.4, "off", 67]],
])
def test_invalid_transitions_fail_validation(edges):
    result = evaluate([event()], edges)
    assert result["edge_anomalies"] and not result["passed"]


@pytest.mark.parametrize("edges", [
    [[1.1, "on", 67], [1.0, "off", 67]], [[float("nan"), "on", 67]],
    [[1.0, "on", True]], [[1.0, "other", 67]],
])
def test_invalid_edges_are_rejected(edges):
    with pytest.raises(ValueError):
        evaluate([event()], edges)


def test_prepare_midi_preserves_rest_durations_and_tempo(tmp_path):
    path = tmp_path / "song.mid"
    track = (b"\x00\xff\x51\x03\x07\xa1\x20"
             b"\x83\x60\x90\x43\x4a\x83\x60\x80\x43\x00"
             b"\x83\x60\xff\x51\x03\x0f\x42\x40"
             b"\x00\x90\x43\x4a\x83\x60\x80\x43\x00\x00\xff\x2f\x00")
    path.write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
                     + b"MTrk" + struct.pack(">I", len(track)) + track)
    output = tmp_path / "prepared"
    assert main(["--stage", "prepare", "--score", str(path), "--output", str(output)]) == 0
    score = yaml.safe_load((output / "score.fingering.yaml").read_text())
    assert [(e["start"], e["end"]) for e in score["events"]] == [(0.5, 1.0), (1.5, 2.5)]
    assert all(e["hand"] == "right" and e["finger"] is None for e in score["events"])
    before = (output / "status.json").read_bytes()
    assert main(["--stage", "prepare", "--score", str(path), "--output", str(output)]) == 1
    assert (output / "status.json").read_bytes() == before


def test_wrong_hand_is_rejected_instead_of_silently_dropping_notes(tmp_path):
    path = tmp_path / "left.yaml"
    target = event()
    target["hand"] = "left"
    path.write_text(yaml.safe_dump({"format": "piano_fingering/1", "events": [target]}))
    with pytest.raises(ValueError, match="belongs to left"):
        load_score(path)


def test_failed_input_has_a_diagnostic_status(tmp_path):
    output = tmp_path / "failed"
    assert main(["--stage", "prepare", "--score", str(tmp_path / "absent.mid"),
                 "--output", str(output)]) == 1
    status = json.loads((output / "status.json").read_text())
    assert status["state"] == "failed" and status["stage"] == "prepare"
    assert status["error"]


def test_all_samples_use_existing_event_schema():
    paths = sorted((PACKAGE / "examples/performance_pipeline").glob("*.yaml"))
    assert len(paths) == 3
    for path in paths:
        assert len(load_score(path)["events"]) == 3


def plan_document():
    return {"format": "piano_performance/1",
            "metadata": {"tempo_scale": 2.0, "timing_tolerance_sec": 0.03},
            "hands": {"right": {
                "ready_state": [0.0] * 20, "arm_start": [0.0] * 7,
                "arm_waypoints": [{"time_sec": 0.0, "move_after_sec": 0.0,
                                   "joints": [0.0] * 7}],
                "hand_states": [],
                "events": [{"id": 7, "note": 67, "finger": "little", "arm_waypoint": 0,
                            "start_sec": 2.0, "end_sec": 2.4}]}}}


def test_existing_plan_time_is_scaled_once_and_optional_velocity_is_supported():
    expected = expected_from_plan(plan_document())
    assert expected[0]["start"] == 4.0
    assert expected[0]["end"] == 4.8
    assert expected[0]["plan_event_id"] == 7
    assert evaluate(expected, [[4.0, "on", 67], [4.8, "off", 67]])["passed"]


def test_evaluate_stage_uses_plan_tempo_and_records_source(tmp_path):
    plan = tmp_path / "plan.yaml"
    plan.write_text(yaml.safe_dump(plan_document()))
    edges = tmp_path / "edges.json"
    edges.write_text(json.dumps([[4.0, "on", 67], [4.8, "off", 67]]))
    output = tmp_path / "evaluation"
    assert main(["--stage", "evaluate", "--plan", str(plan), "--edges", str(edges),
                 "--source", "synthetic", "--output", str(output)]) == 0
    report = json.loads((output / "evaluation.json").read_text())
    assert report["passed"] and report["source"] == "synthetic"


@pytest.mark.parametrize("sim_code", [0, 3, 1])
def test_pipeline_keeps_simulator_failure_even_if_note_score_passes(tmp_path, monkeypatch, sim_code):
    from rm_piano_player import performance_pipeline as pipeline

    output = tmp_path / "run"
    package = PACKAGE.parent / "rm_mujoco"

    def child(name, command, directory, status):
        destination = Path(command[command.index("--output") + 1])
        if name == "plan":
            destination.write_text(yaml.safe_dump(plan_document()))
            return 0
        if sim_code == 1:
            return 1
        destination.mkdir()
        (destination / "report.json").write_text(json.dumps({"passed": sim_code == 0}))
        (destination / "key_edges.json").write_text(
            json.dumps([[4.0, "on", 67], [4.8, "off", 67]]))
        return sim_code

    monkeypatch.setattr(pipeline, "_child", child)
    assert main(["--score", str(PACKAGE / "examples/performance_pipeline/repeated_g.yaml"),
                 "--package", str(package), "--output", str(output)]) == sim_code
    status = json.loads((output / "status.json").read_text())
    assert status["state"] == {0: "completed", 3: "failed_validation", 1: "failed"}[sim_code]
    if sim_code != 1:
        assert status["evaluation_passed"] is True
        assert status["simulation_passed"] is (sim_code == 0)


def test_planning_failure_stops_before_simulation(tmp_path, monkeypatch):
    from rm_piano_player import performance_pipeline as pipeline

    calls = []

    def child(name, command, directory, status):
        calls.append(name)
        return 1

    monkeypatch.setattr(pipeline, "_child", child)
    output = tmp_path / "run"
    assert main(["--score", str(PACKAGE / "examples/performance_pipeline/repeated_g.yaml"),
                 "--package", str(PACKAGE.parent / "rm_mujoco"),
                 "--output", str(output)]) == 1
    assert calls == ["plan"]
    status = json.loads((output / "status.json").read_text())
    assert status["stage"] == "plan" and status["state"] == "failed"


def test_cli_script_prepares_score_in_a_separate_process(tmp_path):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(PACKAGE), str(PACKAGE.parent / "rm_mujoco"), environment.get("PYTHONPATH", "")])
    output = tmp_path / "cli"
    result = subprocess.run(
        [sys.executable, str(PACKAGE / "src/piano_performance.py"), "--stage", "prepare",
         "--score", str(PACKAGE / "examples/performance_pipeline/rest_eg.yaml"),
         "--output", str(output)], env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    status = json.loads((output / "status.json").read_text())
    assert status["score_events"] == 3
    assert status["inputs"]["score"]["sha256"]


def test_child_failure_preserves_log_and_return_code(tmp_path):
    from rm_piano_player.performance_pipeline import _child

    status = {"steps": []}
    assert _child("plan", [sys.executable, "-c",
                           "print('diagnostic failure'); raise SystemExit(7)"],
                  tmp_path, status) == 7
    assert "diagnostic failure" in (tmp_path / "plan.log").read_text()
    recorded = json.loads((tmp_path / "status.json").read_text())
    assert recorded["steps"][0]["exit_code"] == 7
    assert recorded["steps"][0]["wall_seconds"] >= 0


def test_child_is_killed_when_live_output_is_interrupted(tmp_path, monkeypatch):
    from rm_piano_player import performance_pipeline as pipeline

    class Process:
        def __init__(self):
            self.stdout = self
            self.killed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            raise KeyboardInterrupt

        def wait(self):
            return 0

        def kill(self):
            self.killed = True

    process = Process()
    monkeypatch.setattr(pipeline.subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(KeyboardInterrupt):
        pipeline._child("plan", ["child"], tmp_path, {"steps": []})
    assert process.killed


def test_pipeline_forwards_search_limits(tmp_path, monkeypatch):
    from rm_piano_player import performance_pipeline as pipeline

    commands = []

    def child(name, command, directory, status):
        commands.append(command)
        destination = Path(command[command.index("--output") + 1])
        destination.write_text(yaml.safe_dump(plan_document()))
        return 0

    monkeypatch.setattr(pipeline, "_child", child)
    output = tmp_path / "plan"
    assert main(["--stage", "plan", "--score",
                 str(PACKAGE / "examples/performance_pipeline/repeated_g.yaml"),
                 "--package", str(PACKAGE.parent / "rm_mujoco"),
                 "--beam-width", "2", "--candidate-limit", "1",
                 "--output", str(output)]) == 0
    command = commands[0]
    assert command[command.index("--beam-width") + 1] == "2"
    assert command[command.index("--candidate-limit") + 1] == "1"


def test_old_dual_plan_ids_are_unambiguous_in_evaluation():
    import copy

    plan = plan_document()
    left = copy.deepcopy(plan["hands"]["right"])
    left["events"][0]["note"] = 48
    plan["hands"]["left"] = left
    expected = expected_from_plan(plan)
    assert len({e["id"] for e in expected}) == 2
    assert {e["plan_event_id"] for e in expected} == {7}
    result = evaluate(expected, [[4.0, "on", 67], [4.0, "on", 48],
                                 [4.8, "off", 67], [4.8, "off", 48]])
    assert result["passed"]
