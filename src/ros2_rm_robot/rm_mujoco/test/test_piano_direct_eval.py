"""Acceptance tests for single-note direct episodes."""

from types import SimpleNamespace
from pathlib import Path
import sys

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.piano_direct_eval import evaluate_edges, single_note_success  # noqa: E402


def _task():
    return SimpleNamespace(
        origin_sec=0.0,
        events=[SimpleNamespace(note=53, start_sec=0.2, end_sec=0.5)])


def test_correct_edges_pass():
    result = single_note_success(_task(), [(0.198, "on", 53), (0.51, "off", 53)])
    assert result.success
    assert result.onset_error == pytest.approx(-0.002)
    assert result.release_error == pytest.approx(0.01)


def test_late_press_and_early_release_fail():
    assert not single_note_success(_task(), [(0.26, "on", 53), (0.5, "off", 53)]).success
    assert not single_note_success(_task(), [(0.2, "on", 53), (0.45, "off", 53)]).success


def test_missing_or_extra_edges_fail():
    assert not single_note_success(_task(), [(0.5, "off", 53)]).success
    assert not single_note_success(_task(), [(0.2, "on", 53)]).success
    assert not single_note_success(
        _task(), [(0.2, "on", 53), (0.5, "off", 53), (0.3, "on", 55)]).success


def test_safety_failures_fail():
    edges = [(0.2, "on", 53), (0.5, "off", 53)]
    assert not single_note_success(_task(), edges, key_violations=[{"note": 53}]).success
    assert not single_note_success(_task(), edges, other_contacts=[("a", "b")]).success
    assert not single_note_success(_task(), edges, terminated=True).success


def test_rejects_short_hold_and_same_key_retrigger():
    short = [(0.220, "on", 53), (0.484, "off", 53)]
    assert single_note_success(_task(), short).reason == "duration outside tolerance"
    retrigger = [(0.2, "on", 53), (0.32, "off", 53),
                 (0.4, "on", 53), (0.5, "off", 53)]
    assert single_note_success(_task(), retrigger).reason == "unexpected same-key edge"
    assert single_note_success(_task(), [(0.2, "on", 53)]).reason == "missing release"


def test_repeated_note_and_overlapping_chord_need_distinct_physical_intervals():
    task = _task()
    task.events.extend([
        SimpleNamespace(note=53, start_sec=0.6, end_sec=0.8),
        SimpleNamespace(note=56, start_sec=0.49, end_sec=0.7),
    ])
    edges = [(0.2, "on", 53), (0.49, "on", 56), (0.5, "off", 53),
             (0.6, "on", 53), (0.7, "off", 56), (0.8, "off", 53)]
    report = evaluate_edges(task, edges, timestep=0.002)
    assert report["success"]
    assert report["timed_notes"] == 3
    assert len(report["overlaps"]) == 2
    no_overlap = [(0.2, "on", 53), (0.49, "off", 53), (0.50, "on", 56),
                  (0.6, "on", 53), (0.7, "off", 56), (0.8, "off", 53)]
    report = evaluate_edges(task, no_overlap, timestep=0.002)
    assert report["timed_notes"] == 3
    assert not report["success"]
