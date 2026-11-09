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

from rm_mujoco.fingering import FingeringPlanner, PianoHandModel, PlanningError  # noqa: E402
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


def test_short_f5_alternative_has_a_ranking_penalty():
    model = PianoHandModel(PACKAGE, SCENE, SIM_POSE)
    group = [(_event(note=77, finger="ring"), "ring")]
    alternatives = [item for item in model.geometry_candidates("right", group)
                    if "alternative_wrist" in item.detail]
    preferred = next(item for item in alternatives if item.detail["next_note"] is None)
    fallback = next(item for item in alternatives if item.detail["next_note"] == 76)
    assert fallback.cost > preferred.cost


def test_g4_little_uses_the_simulation_depth_calibration():
    model = PianoHandModel(PACKAGE, SCENE, SIM_POSE)
    state = model.compose(["little"], [67])
    assert state[4] == pytest.approx(143.35)
    assert state[19] == pytest.approx(136.3)
    assert model.note_timing[(67, "little")] == pytest.approx((0.050, 0.090))


def test_d4_index_uses_the_simulation_depth_calibration():
    model = PianoHandModel(PACKAGE, SCENE, SIM_POSE)
    state = model.compose(["index"], [62])
    assert state[1] == pytest.approx(174.6)
    assert state[15] == pytest.approx(114.4)


def test_budget_expiry_identifies_the_unfinished_hand(hand_model, monkeypatch):
    from types import SimpleNamespace

    from rm_mujoco import fingering

    times = iter((0.0, 1.0))
    monkeypatch.setattr(fingering, "time", SimpleNamespace(monotonic=lambda: next(times)))
    planner = FingeringPlanner(hand_model, planning_budget_sec=0.5)
    with pytest.raises(PlanningError, match=r"budget exhausted \(0.5 s\) during right hand"):
        planner.plan([_event()])


def test_plan_hand_rejects_an_empty_initial_beam(hand_model):
    planner = FingeringPlanner(hand_model)
    with pytest.raises(ValueError, match="initial_beam must not be empty"):
        planner._plan_hand("right", [], initial_beam=[])


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

    progress = []
    planner = FingeringPlanner(
        hand_model, beam_width=2, candidate_limit=2,
        progress=lambda **update: progress.append(update))
    plan = planner.plan([_event()], source="single-note-test")
    validate_plan(plan)
    runner = PlanRunner(
        plan, PACKAGE, SCENE, MODEL, 1.0, 0.03, None, None)
    report = runner.run()
    assert report["passed"], report
    assert len(report["observed"]) == 1
    assert report["observed"][0]["note"] == 60
    assert len(progress) == 1
    assert progress[0]["group_count"] == 1
    assert progress[0]["beam_width"] >= 1


def test_direct_planning_defaults_to_simulation_poses(monkeypatch):
    import plan_performance

    monkeypatch.setattr(plan_performance, "get_package_share_directory", None)
    assert plan_performance._default_pose_file() == SIM_POSE


def test_both_hands_plan_requires_observed_ownership_in_shared_playback(hand_model):
    from rm_mujoco.performance import validate_plan
    from run_performance import PlanRunner

    events = [
        _event(note=72, finger="index", start=0.0, end=0.821),
        {**_event(note=48, finger="index", start=0.0, end=0.7, event_id=2), "hand": "left"},
    ]
    reports = []

    def check(plan):
        validate_plan(plan)
        runner = PlanRunner(plan, PACKAGE, SCENE, MODEL, 1.0, 0.03, None, None)
        report = runner.run()
        reports.append(report)
        return report

    planner = FingeringPlanner(hand_model, beam_width=4, fingering_mode="fixed")
    plan = planner.plan(events, hand="both", joint_check=check)
    assert set(plan["hands"]) == {"left", "right"}
    assert reports[-1]["passed"]
    assert [(item["note"], item["observed_hands"]) for item in reports[-1]["observed"]] == [
        (48, ["left"]), (72, ["right"]),
    ]
    for item in reports[-1]["observed"]:
        assert {"side": item["side"], "finger": "index"} in item["observed_fingers"]


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


def test_observed_spans_keep_extra_and_unmatched_notes():
    from run_performance import observed_note_spans

    edges = [(1.0, "on", 60), (1.25, "on", 61), (1.5, "off", 60),
             (1.75, "on", 62), (2.0, "off", 61)]
    assert observed_note_spans(edges) == [(1.0, 60, 0.5), (1.25, 61, 0.75)]
    assert observed_note_spans(edges, end_time=2.25) == [
        (1.0, 60, 0.5), (1.25, 61, 0.75), (1.75, 62, 0.5)]


def test_pose_specific_lift_is_used_before_press_and_after_release(hand_model):
    from rm_mujoco.fingering import Candidate

    planner = FingeringPlanner(hand_model)
    event = _event(note=72, finger="index", start=0., end=.8)
    shape = hand_model.compose(["index"], [72])
    lift = hand_model.compose([])
    lift[1] = 223.
    candidate = Candidate(hand_model.ready_arm_q["right"], shape, (0, 0, 0), 0.,
                          {"lift_positions": lift, "prepare_transition_sec": .025})
    entry = {"assignments": [(event, "index")], "candidate": candidate,
             "press_sec": .95, "release_secs": {1: 1.73}, "transition_sec": .04,
             "pose_event_ids": {1}, "prepare_sec": .89}
    states = planner._hand_states([entry], .002)
    assert [item["time_sec"] for item in states] == pytest.approx([.89, .95, 1.73])
    assert states[0]["pressed"] == states[2]["pressed"] == []
    assert states[0]["positions"] == states[2]["positions"] == lift
    assert states[0]["transition_sec"] == .025
    assert states[1]["positions"] == shape


def test_lift_preparation_rejects_a_command_collision(hand_model):
    from rm_mujoco.fingering import Candidate

    planner = FingeringPlanner(hand_model)
    event = _event(note=72, finger="index", start=0., end=.8)
    candidate = Candidate(hand_model.ready_arm_q["right"],
                          hand_model.compose(["index"], [72]), (0, 0, 0), 0.,
                          {"lift_positions": hand_model.compose([])})
    entry = {"assignments": [(event, "index")], "candidate": candidate,
             "press_sec": .95, "release_secs": {1: 1.73}, "transition_sec": .04,
             "pose_event_ids": {1}, "prepare_sec": .949}
    with pytest.raises(PlanningError, match="physics step"):
        planner._hand_states([entry], .002)
