"""Check the MuJoCo hand model, candidate planner and a single-note playback."""

from pathlib import Path
import sys

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
SCENE = PACKAGE / "config/piano_scene.yaml"
POSE = PACKAGE.parent / "rm_piano_player/config/right_hand_ode_to_joy.yaml"
SIM_POSE = PACKAGE / "config/right_hand_piano_sim.yaml"
MODEL = PACKAGE / "models/rm_75_6fb_v_dual_l20.xml"
CHORD_MELODY = PACKAGE / "test/fixtures/chord_melody.fingering.yaml"
WIDE_MELODY = PACKAGE / "test/fixtures/wide_melody.fingering.yaml"
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "scripts"))

from rm_mujoco.fingering import FingeringPlanner, PianoHandModel  # noqa: E402
from rm_mujoco.performance_runtime import HandTrack, KeyTravelMonitor  # noqa: E402


@pytest.fixture(scope="module")
def hand_model():
    return PianoHandModel(PACKAGE, SCENE, POSE)


def _event(note=60, finger="thumb", start=1.0, end=1.6, event_id=1):
    return {"id": event_id, "hand": "right", "start": start, "end": end,
            "note": note, "velocity": 80, "finger": finger}


def test_a_single_finger_state_is_the_calibrated_press(hand_model):
    state = hand_model.compose(["middle"])
    assert state == pytest.approx(hand_model.press20["middle"].tolist())
    both = hand_model.compose(["middle", "little"])
    for index, value in enumerate(both):
        expected = (hand_model.ready20[index] + hand_model.delta["middle"][index]
                    + hand_model.delta["little"][index])
        assert value == pytest.approx(min(255.0, max(0.0, expected)))


def test_finger_order_prefers_the_prior_then_pitch(hand_model):
    assert hand_model.finger_order(60, "thumb")[0] == "thumb"
    assert hand_model.finger_order(60, None)[0] == "thumb"
    assert hand_model.finger_order(67, "little")[0] == "little"


def test_a_short_command_starts_from_the_interrupted_value():
    track = HandTrack(
        [0.0], [{"time_sec": 0.10, "positions": [100.0]},
                {"time_sec": 0.12, "positions": [0.0]}], 0.04)
    assert track.at(0.12)[0] == pytest.approx(50.0)
    assert track.at(0.14)[0] == pytest.approx(25.0)
    assert track.at(0.16)[0] == pytest.approx(0.0)


def test_short_note_with_good_duration_shifts_without_changing_pulse(hand_model):
    planner = FingeringPlanner(hand_model)
    press, releases = planner._correct_timing(
        1.50625, {4: 1.555208},
        {4: {"on_error": 0.02775, "off_error": 0.034792,
             "duration_error": 0.007042, "duration_tolerance": 0.0122395}},
        0.002)
    assert press == pytest.approx(1.50025)
    assert releases[4] == pytest.approx(1.549208)


def test_key_rebound_allowance_does_not_relax_the_press_limit(hand_model):
    import math

    sim = hand_model.reset_work()
    travel = KeyTravelMonitor(hand_model.model)
    sim.qpos[hand_model.key_qpos[60]] = -math.radians(0.134)
    sim.qpos[hand_model.key_qpos[62]] = hand_model.key_limit[62] + math.radians(0.001)
    sim.qpos[hand_model.key_qpos[64]] = -math.radians(0.136)
    travel.observe(sim)
    assert [item["note"] for item in travel.violations()] == [62, 64]


def test_c4_index_candidate_is_clean_and_sounds(hand_model):
    candidate = hand_model.candidate_group(
        "right", [(_event(), "index")], hand_model.ready_arm_q["right"])
    assert candidate is not None, "C4 index candidate was expected to be reachable"
    ok, detail = hand_model.check_group(
        "right", [(60, "index")], candidate.arm_q, candidate.hand20, strict=True)
    assert ok, detail
    probe, probe_detail = hand_model.dynamic_probe(
        "right", [60], candidate.arm_q, candidate.hand20)
    assert probe, probe_detail


def test_single_note_plan_and_mujoco_playback(hand_model):
    from rm_mujoco.performance import validate_plan
    from run_performance import PlanRunner

    planner = FingeringPlanner(hand_model, beam_width=2, candidate_limit=2)
    plan = planner.plan([_event()], source="single-note-test")
    validate_plan(plan)
    runner = PlanRunner(
        plan, PACKAGE, SCENE, MODEL, 1.0, 0.03, None, None)
    report = runner.run()
    assert report["passed"], report
    assert len(report["observed"]) == 1
    assert report["observed"][0]["note"] == 60


def test_calibrated_chord_and_melody_pass_in_mujoco():
    from rm_mujoco.performance import load_events, validate_plan
    from run_performance import PlanRunner

    hand_model = PianoHandModel(PACKAGE, SCENE, SIM_POSE)
    events = load_events(CHORD_MELODY)
    planner = FingeringPlanner(
        hand_model, beam_width=4, candidate_limit=2)
    plan = planner.plan(events["events"], source=CHORD_MELODY)
    validate_plan(plan)
    runner = PlanRunner(
        plan, PACKAGE, SCENE, MODEL, 1.0, 0.03, None, None)
    report = runner.run()
    assert report["passed"], report
    assert len(report["observed"]) == 5
    assert len(report["same_hand_chords"]) == 1
    assert not report["missing"]
    assert not report["unexpected"]
    assert not report["arm_moves_over_held_notes"]
    assert not report["wrong_finger_contacts"]


def test_wide_melody_with_calibrated_c4_passes():
    from rm_mujoco.performance import load_events, validate_plan
    from run_performance import PlanRunner

    hand_model = PianoHandModel(PACKAGE, SCENE, SIM_POSE)
    events = load_events(WIDE_MELODY)
    planner = FingeringPlanner(
        hand_model, beam_width=4, candidate_limit=3, arm_lead=0.15)
    plan = planner.plan(events["events"], source=WIDE_MELODY)
    validate_plan(plan)
    runner = PlanRunner(
        plan, PACKAGE, SCENE, MODEL, 1.0, 0.03, None, None)
    report = runner.run()
    assert report["passed"], report
    assert len(report["observed"]) == 6
    assert len(report["same_hand_chords"]) == 1
    assert not report["missing"]
    assert not report["unexpected"]
    assert not report["arm_moves_over_held_notes"]
    assert not report["wrong_finger_contacts"]
    assert not report["active_keys_at_end"]
    c4_edges = [edge for edge in runner.edges if edge[2] == 60]
    assert [edge[1] for edge in c4_edges] == ["on", "off"]
    assert report["all_key_angle_max_deg"]["65"] < 2.102404550778664
