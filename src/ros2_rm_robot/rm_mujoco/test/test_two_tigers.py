"""Input gates for the frozen, continuous dual-hand performance."""

import copy
from pathlib import Path
import sys

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "scripts"))

from rm_mujoco.performance import load_events, load_plan  # noqa: E402
from verify_two_tigers import BASELINE, check_score, file_hash, load_baseline, main  # noqa: E402


def test_baseline_identity_and_full_score():
    plan, _ = load_baseline(PACKAGE)
    assert sum(len(hand["events"]) for hand in plan["hands"].values()) == 40


@pytest.mark.parametrize("change", ["finger", "time", "missing", "duplicate", "tempo"])
def test_rejects_changed_performance(change):
    score = load_events(PACKAGE / BASELINE / "score.yaml")
    plan = copy.deepcopy(load_plan(PACKAGE / BASELINE / "performance.yaml"))
    events = plan["hands"]["right"]["events"]
    if change == "finger":
        events[0]["finger"] = "little"
    elif change == "time":
        events[0]["start_sec"] += 0.01
    elif change == "missing":
        events.pop()
    elif change == "duplicate":
        events[-1] = copy.deepcopy(events[0])
    else:
        plan["metadata"]["tempo_scale"] = 2.0
    with pytest.raises(ValueError):
        check_score(score, plan)


def test_existing_output_is_never_reused(tmp_path):
    sentinel = tmp_path / "report.json"
    sentinel.write_text("old result", encoding="utf-8")
    assert main(["--package", str(PACKAGE), "--output", str(tmp_path)]) == 1
    assert sentinel.read_text(encoding="utf-8") == "old result"
    assert not (tmp_path / "plan.yaml").exists()


def test_text_hash_survives_checkout_line_endings(tmp_path):
    path = tmp_path / "file.yaml"
    path.write_bytes(b"a: 1\n")
    original = file_hash(path)
    path.write_bytes(b"a: 1\r\n")
    assert file_hash(path) == original
    path.write_bytes(b"a: 2\n")
    assert file_hash(path) != original
