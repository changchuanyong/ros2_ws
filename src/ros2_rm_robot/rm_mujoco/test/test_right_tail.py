"""Verify the calibrated right-hand tail plans through the production scheduler."""

from pathlib import Path
import sys

import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
SCENE = PACKAGE / "config/piano_scene.yaml"
SIM_POSE = PACKAGE / "config/right_hand_piano_sim.yaml"
TAIL = PACKAGE / "config/right_tail_v29.yaml"
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "scripts"))

from rm_mujoco.fingering import PianoHandModel  # noqa: E402
from rm_mujoco.performance import validate_plan  # noqa: E402
import verify_right_tail  # noqa: E402


@pytest.fixture(scope="module")
def hand_model():
    return PianoHandModel(PACKAGE, SCENE, SIM_POSE)


def test_tail_calibration_lists_the_six_two_tigers_events():
    spec = verify_right_tail.load_tail(TAIL)
    assert [item["id"] for item in spec["events"]] == [33, 35, 36, 37, 39, 40]
    assert [item["note"] for item in spec["events"]] == [72, 67, 72, 72, 67, 72]
    assert [item["pose"] for item in spec["events"]] == [
        "c_before_g", "g", "c", "c", "g", "c"]
    assert spec["lift"] == pytest.approx(30.0)
    assert spec["leads"][39] == pytest.approx([0.05, 0.03])
    assert spec["events"][4]["transition_sec"] == pytest.approx(0.03)


def test_tail_lift_raises_only_the_index_channel():
    spec = verify_right_tail.load_tail(TAIL)
    press = spec["poses"]["c"]["positions"]
    lift = verify_right_tail.lift_positions(spec, "c")
    assert lift[1] == pytest.approx(min(255.0, press[1] + 30.0))
    assert lift[:1] + lift[2:] == press[:1] + press[2:]


def test_tail_calibration_rejects_a_short_pose(tmp_path):
    document = yaml.safe_load(TAIL.read_text(encoding="utf-8"))
    document["poses"]["c"]["positions"] = document["poses"]["c"]["positions"][:19]
    broken = tmp_path / "broken.yaml"
    broken.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match=r"poses\.c\.positions"):
        verify_right_tail.load_tail(broken)


def test_tail_calibration_rejects_a_pose_without_prepare_timing(tmp_path):
    document = yaml.safe_load(TAIL.read_text(encoding="utf-8"))
    del document["timing"]["prepare"]["g"]
    broken = tmp_path / "broken.yaml"
    broken.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="has no prepare timing"):
        verify_right_tail.load_tail(broken)


def test_calibrated_tail_plans_and_validates(hand_model):
    spec = verify_right_tail.load_tail(TAIL)
    plan, _ = verify_right_tail.schedule(hand_model, spec, TAIL)
    assert plan is not None, "the calibrated tail must schedule completely"
    side = plan["hands"]["right"]
    assert [item["id"] for item in side["events"]] == [33, 35, 36, 37, 39, 40]
    validate_plan(plan)
