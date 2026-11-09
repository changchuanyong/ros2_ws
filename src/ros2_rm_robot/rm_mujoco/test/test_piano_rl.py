"""Unit and MuJoCo smoke tests for residual piano reinforcement learning."""

from pathlib import Path
import importlib.util
import json
import sys

import pytest

mujoco = pytest.importorskip("mujoco")
np = pytest.importorskip("numpy")
pytest.importorskip("gymnasium")

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.performance import write_plan  # noqa: E402
from rm_mujoco.piano_rl import (  # noqa: E402
    PianoResidualEnv, PianoTaskCycle, target_keys, tolerance, key_reward, episode_steps, finger_clock,
    active_fingers, f1_score,
)


@pytest.fixture
def plan_path(tmp_path):
    path = tmp_path / "single_note.performance.yaml"
    plan = {
        "format": "piano_performance/1",
        "metadata": {
            "tempo_scale": 1.0,
            "start_padding_sec": 0.2,
            "timing_tolerance_sec": 0.03,
        },
        "hands": {
            "right": {
                "ready_state": [0.0] * 20,
                "arm_start": [0.0] * 7,
                "arm_waypoints": [{
                    "time_sec": 0.0,
                    "move_after_sec": 0.0,
                    "joints": [0.0] * 7,
                }],
                "hand_states": [
                    {"time_sec": 0.0, "pressed": [], "positions": [0.0] * 20},
                    {"time_sec": 0.18, "pressed": ["index"],
                     "positions": [0.0] * 20, "transition_sec": 0.02},
                    {"time_sec": 0.42, "pressed": [], "positions": [0.0] * 20},
                ],
                "events": [{
                    "id": 1,
                    "note": 60,
                    "start_sec": 0.2,
                    "end_sec": 0.4,
                    "velocity": 64,
                    "finger": "index",
                    "prior_finger": "index",
                    "arm_waypoint": 0,
                }],
            },
        },
    }
    write_plan(path, plan)
    return path


def test_robopianist_tolerance_boundaries():
    assert tolerance(0.005, 0.01, 0.1) == 1.0
    assert tolerance(0.01, 0.01, 0.1) == 1.0
    assert tolerance(0.11, 0.01, 0.1) == pytest.approx(0.1)
    assert tolerance(0.21, 0.01, 0.1) < tolerance(0.11, 0.01, 0.1)


def test_target_keys_respect_note_interval():
    events = [{"note": 60, "on": 0.2, "off": 0.4}]
    assert target_keys(events, 0.19).sum() == 0
    assert target_keys(events, 0.2)[39] == 1
    assert target_keys(events, 0.39)[39] == 1
    assert target_keys(events, 0.4).sum() == 0


def test_threshold_wrong_ignores_silent_touch_but_not_overpressure():
    target = np.zeros(3)
    assert key_reward(np.array([0.1, 0.2, 0.3]), target, True) == 1.0
    assert key_reward(np.array([0.6, 0.2, 0.3]), target, True) == -2.0
    assert key_reward(np.array([0.6, 0.7, 0.8]), target, True) == -2.0
    assert key_reward(np.array([1.1, 0.0, 0.0]), target, True) < -2.0


@pytest.mark.parametrize("robopianist_reward", [False, True])
def test_environment_api(plan_path, robopianist_reward):
    check_env = pytest.importorskip(
        "stable_baselines3.common.env_checker").check_env
    env = PianoResidualEnv(
        plan_path, PACKAGE, robopianist_reward=robopianist_reward)
    try:
        check_env(env, warn=True, skip_render_check=True)
    finally:
        env.close()


def test_active_fingertip_distance_and_energy(plan_path):
    env = PianoResidualEnv(plan_path, PACKAGE, robopianist_reward=True)
    try:
        env.reset(seed=0)
        assert env._finger_reward() == 0.0
        while env.runner.data.time < 0.22:
            env.step(np.full(20, 0.1, dtype=np.float32))
        assert 0.0 <= env._finger_reward() <= 1.0
        assert env.fingertip_distance_samples > 0
        assert env.fingertip_distance_total > 0.0
        assert env.energy_samples > 0
        assert env.energy_total > 0.0
        assert env.reward_components["finger"] >= 0.0
        assert env.reward_components["energy"] < 0.0
    finally:
        env.close()


def test_default_reward_keeps_shaping_disabled(plan_path):
    env = PianoResidualEnv(plan_path, PACKAGE)
    try:
        env.reset(seed=0)
        env.step(np.zeros(20, dtype=np.float32))
        assert env.fingertip == {}
        assert env.reward_components["finger"] == 0.0
        assert env.reward_components["energy"] == 0.0
    finally:
        env.close()


def test_event_credit_waits_for_acceptance_deadline(plan_path):
    env = PianoResidualEnv(plan_path, PACKAGE)
    try:
        env.reset(seed=0)
        assert env._event_potential() == 0.0
        env.runner.edges = [(0.2, "on", 60), (0.4, "off", 60)]
        env.runner.data.time = 0.42
        assert env._event_potential() == 0.0
        env.runner.data.time = 0.44
        assert env._event_potential() == 5.0
        assert env._event_potential() == 5.0
    finally:
        env.close()


def test_event_credit_detects_duration_error_with_legal_edges(plan_path):
    env = PianoResidualEnv(plan_path, PACKAGE)
    try:
        env.reset(seed=0)
        env.runner.edges = [(0.18, "on", 60), (0.42, "off", 60)]
        env.runner.data.time = 0.46
        report = env.runner._report()
        assert [item["kind"] for item in report["unexpected"]] == ["duration"]
        assert env._event_potential() < 0.0
        env.runner.edges = []
        assert env._event_potential() < 0.0
    finally:
        env.close()


def test_event_credit_balances_episode_return(plan_path):
    env = PianoResidualEnv(plan_path, PACKAGE)
    try:
        env.reset(seed=0)
        done = False
        while not done:
            _, _, done, _, info = env.step(np.zeros(20, dtype=np.float32))
        assert env.reward_components["event"] == pytest.approx(env._event_potential())
        assert sum(info["reward_components"].values()) == pytest.approx(
            env.episode_return)
    finally:
        env.close()


@pytest.fixture
def training_entry():
    spec = importlib.util.spec_from_file_location(
        "train_piano_rl_test", PACKAGE / "scripts/train_piano_rl.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initial_policy_reproduces_zero_residual(plan_path, training_entry):
    pytest.importorskip("stable_baselines3")
    env = PianoResidualEnv(plan_path, PACKAGE)
    try:
        policy = training_entry.create_policy(env, seed=7)
        obs, _ = env.reset(seed=0)
        for observation in (obs, np.ones_like(obs), -np.ones_like(obs)):
            action, _ = policy.predict(observation, deterministic=True)
            np.testing.assert_array_equal(action, np.zeros(20, dtype=np.float32))
    finally:
        env.close()


def test_evaluation_distinguishes_timing_from_extra_notes(
        plan_path, training_entry, tmp_path, monkeypatch):
    env = PianoResidualEnv(plan_path, PACKAGE)
    original_report = env.replay.PlanRunner._report

    def report_with_sensor_edges(runner):
        runner.edges = [(0.18, "on", 60), (0.42, "off", 60),
                        (0.3, "on", 61), (0.32, "off", 61)]
        return original_report(runner)

    monkeypatch.setattr(env.replay.PlanRunner, "_report", report_with_sensor_edges)
    try:
        summary = training_entry.evaluate(env, None, tmp_path / "evaluation")
        assert summary["unexpected_by_kind"] == {"duration": 1, "extra": 1}
        assert summary["unexpected"] == sum(summary["unexpected_by_kind"].values())
        assert summary["matched"] == summary["expected"] - summary["missing"]
    finally:
        env.close()


@pytest.mark.parametrize("reference_passed", [False, True])
def test_cli_fails_closed_on_physical_rejection(
        plan_path, training_entry, tmp_path, monkeypatch, reference_passed):
    checker = pytest.importorskip("stable_baselines3.common.env_checker")
    learned = []

    class Policy:
        def set_logger(self, logger):
            pass

        def learn(self, **kwargs):
            learned.append(True)

        def save(self, path):
            pass

        num_timesteps = 512

    monkeypatch.setattr(checker, "check_env", lambda *args, **kwargs: None)
    monkeypatch.setattr(training_entry, "create_policy", lambda *args: Policy())
    monkeypatch.setattr(training_entry, "load_experiment", lambda path: {
        "train": [plan_path], "validation": [plan_path]})
    def fake_evaluate(env, policy, output, *, seed=0):
        output.mkdir(parents=True, exist_ok=False)
        if reference_passed and policy is None:
            env.reset(seed=0)
            env.set_nominal_trace(np.repeat(env.runner.data.qpos[None, :],
                                           episode_steps(env.plan, env.control_dt) + 1, axis=0))
        return {"passed": reference_passed and policy is None, "missing": 0, "unexpected": 1,
                "angle_violations": [], "active_keys_at_end": [], "wrong_finger_contacts": 0,
                "unexpected_contacts": 0, "max_onset_error_sec": 0.0, "max_release_error_sec": 0.0}

    monkeypatch.setattr(training_entry, "evaluate", fake_evaluate)
    from stable_baselines3 import PPO
    monkeypatch.setattr(PPO, "load", lambda *args, **kwargs: Policy())
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    output = tmp_path / "run"
    assert training_entry.main([
        "--manifest", str(manifest), "--output", str(output), "--steps", "1",
    ]) == 2
    assert bool(learned) == reference_passed
    assert json.loads((output / "config.json").read_text())["command_bias"] == 0.5
    summary = json.loads((output / "summary.json").read_text())
    assert summary["acceptance"]["reference_passed"] == reference_passed
    if reference_passed:
        assert summary["acceptance"]["learned_passed"] is False
    else:
        assert "learned" not in summary["train"][0]


def test_dual_actions_and_reproducible_bias():
    plan = PACKAGE / "examples/two_tigers_flat_palms/verified_40/performance.yaml"
    env = PianoResidualEnv(plan, PACKAGE, command_bias=0.5, robopianist_reward=True)
    try:
        obs, _ = env.reset(seed=101)
        bias = env.bias.copy()
        assert env.sides == ("right", "left")
        assert env.action_space.shape == (20,)
        assert obs.shape == env.observation_space.shape
        assert len(env.fingertip) == 10
        env.step(np.zeros(20, dtype=np.float32))
        env.reset(seed=101)
        np.testing.assert_array_equal(bias, env.bias)
        env.reset(seed=102)
        assert not np.array_equal(bias, env.bias)
        with pytest.raises(ValueError):
            env.step(np.zeros(10, dtype=np.float32))
    finally:
        env.close()


def test_model_selection_prefers_physical_acceptance(training_entry):
    good = dict(passed=True, missing=0, unexpected=0, angle_violations=[],
                active_keys_at_end=[], wrong_finger_contacts=0, unexpected_contacts=0,
                max_onset_error_sec=0.03, max_release_error_sec=0.02, episode_return=1)
    bad = dict(good, passed=False, unexpected=1, episode_return=1000)
    assert training_entry.physical_rank([good]) < training_entry.physical_rank([bad])


def test_dual_zero_residual_records_striking_hand():
    plan = PACKAGE / "examples/two_tigers_flat_palms/verified_40/performance.yaml"
    env = PianoResidualEnv(plan, PACKAGE)
    try:
        env.reset(seed=0)
        while env.runner.data.time < 1.1:
            env.step(np.zeros(20, dtype=np.float32))
        strikes = env.runner.onset_contacts
        assert {note for _, note in strikes} == {48, 72}
        for (_, note), (_, contacts) in strikes.items():
            assert {contact[0] for contact in contacts} == ({"left"} if note == 48 else {"right"})
    finally:
        env.close()


def test_shared_interface_masks_an_absent_hand(plan_path):
    single = PianoResidualEnv(plan_path, PACKAGE)
    dual = PianoResidualEnv(
        PACKAGE / "examples/two_tigers_flat_palms/verified_40/performance.yaml", PACKAGE)
    try:
        assert single.observation_space == dual.observation_space
        assert single.action_space == dual.action_space
        obs, _ = single.reset(seed=7)
        expected = single.step(np.zeros(20, np.float32))[0]
        single.reset(seed=7)
        actual = single.step(np.concatenate([np.zeros(10), np.ones(10)]))[0]
        np.testing.assert_array_equal(actual, expected)
        assert obs[-3:-1].tolist() == [1.0, 0.0]
    finally:
        single.close()
        dual.close()


def test_rollout_covers_the_late_failing_note(training_entry):
    from rm_mujoco.performance import load_plan
    plan = load_plan(PACKAGE / "examples/two_tigers_flat_palms/verified_40/performance.yaml")
    length = episode_steps(plan, 0.02)
    assert 512 < length <= training_entry.rollout_length([length]) == 2048


def test_finger_clock_exposes_release_countdown():
    events = [{"side": "right", "finger": "index", "note": 60,
               "on": 0.2, "off": 0.4}]
    before = finger_clock(events, "right", 0.1).reshape(5, 4)[1]
    held = finger_clock(events, "right", 0.3).reshape(5, 4)[1]
    assert before[1] == pytest.approx(0.25)
    assert before[3] == 0
    assert held[2] == pytest.approx(0.25)
    assert held[3] == 1
    assert not finger_clock(events, "left", 0.3).any()


def test_timing_shaping_prefers_margin_even_when_both_pass(plan_path):
    env = PianoResidualEnv(plan_path, PACKAGE)
    try:
        env.reset(seed=0)
        env.runner.data.time = 0.46
        env.runner.edges = [(0.2, "on", 60), (0.4, "off", 60)]
        exact = env._timing_potential()
        env.runner.edges = [(0.21, "on", 60), (0.4, "off", 60)]
        assert exact > env._timing_potential()
        assert not env.runner._report()["unexpected"]
    finally:
        env.close()


def test_completed_episode_reports_note_coverage(plan_path):
    env = PianoResidualEnv(plan_path, PACKAGE)
    try:
        env.reset(seed=0)
        while not env.done:
            env.step(np.zeros(20, np.float32))
        assert env.completed_episodes == 1
        assert env.seen_events == {("right", 1)}
        assert env.total_control_steps == len(env.action_trace)
    finally:
        env.close()


def test_manifest_isolates_recordings_pieces_and_final_test(
        plan_path, training_entry, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    metadata = {}
    manifest = {"format": "piano_rl_dataset/2", "dataset": "data"}
    for phase, split in [("train", "train"), ("validation", "valid"), ("test", "test")]:
        source = data / f"{phase}.tsv"
        source.write_text("onset\tkey_offset\tframe_offset\tnote\tvelocity\thand\tfinger\n"
                          "0\t0.2\t0.8\t60\t64\tR\t2\n")
        metadata[phase] = {"record_time": phase, "split": split,
                           "composer": "composer", "piece": phase}
        manifest[phase] = [{"source": source.name,
                            "source_sha256": training_entry.sha256(source),
                            "plan": plan_path.name, "plan_sha256": training_entry.sha256(plan_path),
                            "origin_sec": 0.0}]
    metadata_path = data / "metadata.json"
    metadata_path.write_text(json.dumps(metadata))
    manifest["metadata_sha256"] = training_entry.sha256(metadata_path)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    assert len(training_entry.load_experiment(path)["test"]) == 1
    source = data / "test.tsv"
    original = source.read_text()
    source.write_text(original + "0.1\t0.18\t0.8\t62\t64\tR\t3\n")
    manifest["test"][0]["source_sha256"] = training_entry.sha256(source)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="boundary drops source notes"):
        training_entry.load_experiment(path)
    source.write_text(original)
    manifest["test"][0]["source_sha256"] = training_entry.sha256(source)
    metadata["test"]["piece"] = "train"
    metadata_path.write_text(json.dumps(metadata))
    manifest["metadata_sha256"] = training_entry.sha256(metadata_path)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="pieces must be disjoint"):
        training_entry.load_experiment(path)


def test_selection_never_trades_clean_acceptance_for_perturbation(training_entry):
    good = dict(passed=True, missing=0, unexpected=0, angle_violations=[],
                active_keys_at_end=[], wrong_finger_contacts=0, unexpected_contacts=0,
                max_onset_error_sec=0.02, max_release_error_sec=0.02)
    bad = dict(good, passed=False, unexpected=1)
    assert training_entry.selection_rank([good], [bad]) < training_entry.selection_rank([bad], [good])


def test_curriculum_visits_every_task_and_reseeds(plan_path, training_entry):
    first = PianoResidualEnv(
        PACKAGE / "examples/two_tigers_flat_palms/verified_40/performance.yaml", PACKAGE)
    second = PianoResidualEnv(plan_path, PACKAGE)
    env = PianoTaskCycle([first, second])
    try:
        obs, info = env.reset(seed=7)
        assert info["task_index"] == 0
        assert obs[-3:-1].tolist() == [1.0, 1.0]
        obs, info = env.reset()
        assert info["task_index"] == 1
        assert obs[-3:-1].tolist() == [1.0, 0.0]
        assert training_entry.training_tasks(env) == [first, second]
        assert env.reset(seed=7)[1]["task_index"] == 0
    finally:
        env.close()


def test_excerpt_selector_never_drops_a_later_overlapping_onset():
    sys.path.insert(0, str(PACKAGE / "scripts"))
    import prepare_piano_rl
    rows = [dict(onset=0.0, key_offset=0.3, note=65, hand="R", finger="1"),
            dict(onset=0.2, key_offset=0.4, note=67, hand="R", finger="2")]
    assert not prepare_piano_rl.candidate_windows(rows)
    rows[1]["onset"] = 0.5
    rows[1]["key_offset"] = 0.8
    assert prepare_piano_rl.candidate_windows(rows)


def test_nominal_tracking_suppresses_arbitrary_residual_without_bias(plan_path):
    env = PianoResidualEnv(plan_path, PACKAGE)
    try:
        env.reset(seed=0)
        positions = [env.runner.data.qpos.copy()]
        while not env.done:
            env.step(np.zeros(20, np.float32))
            positions.append(env.runner.data.qpos.copy())
        env.set_nominal_trace(positions)
        env.reset(seed=0)
        for index in range(10):
            env.step(np.ones(20, np.float32))
            np.testing.assert_array_equal(env.runner.data.qpos, positions[index + 1])
            assert env.action_trace[-1]["tracking_gate"] == 0.0
        env.runner.data.qpos[env.runner.hand_qpos["right"][0]] += 0.001
        assert np.max(np.abs(env.reference_error())) > 0.0009
        env.step(np.ones(20, np.float32))
        assert env.action_trace[-1]["tracking_gate"] > 0.0
    finally:
        env.close()


def test_pressure_shaping_prefers_margin_below_the_unchanged_limit():
    target = np.ones(1)
    assert key_reward(np.array([0.6]), target) > key_reward(np.array([0.95]), target)


def test_active_finger_labels_match_future_note_intervals():
    events = [{"side": "right", "finger": "middle", "prior_finger": "index",
               "note": 60, "on": 0.2, "off": 0.4}]
    assert not active_fingers(events, "right", 0.19).any()
    assert active_fingers(events, "right", 0.2)[1] == 1.0
    assert active_fingers(events, "right", 0.39)[1] == 1.0
    assert not active_fingers(events, "right", 0.4).any()
    assert not active_fingers(events, "left", 0.3).any()


def test_frame_level_f1_counts_false_positives_and_negatives():
    metrics = f1_score(np.array([8, 2, 2]))
    assert metrics["precision"] == pytest.approx(0.8)
    assert metrics["recall"] == pytest.approx(0.8)
    assert metrics["f1"] == pytest.approx(0.8)
    assert f1_score(np.zeros(3))["f1"] == 1.0
    json.dumps(metrics)


def test_robopianist_profile_is_explicit_and_supports_discount_ablation(training_entry):
    default = training_entry.ppo_configuration()
    profile = training_entry.ppo_configuration(True)
    assert default["network_width"] == 64
    assert profile["network_width"] == 256
    assert profile["network_depth"] == 3
    assert profile["batch_size"] == 256
    assert profile["learning_rate"] == pytest.approx(3e-4)
    assert profile["activation"] == "relu"
    assert training_entry.ppo_configuration(True, 0.9)["gamma"] == pytest.approx(0.9)
    with pytest.raises(ValueError):
        training_entry.ppo_configuration(gamma=0.0)


def test_selection_rejects_a_regression_on_the_worst_task(training_entry):
    good = dict(passed=True, missing=0, unexpected=0, angle_violations=[],
                active_keys_at_end=[], wrong_finger_contacts=0, unexpected_contacts=0,
                max_onset_error_sec=0.02, max_release_error_sec=0.02, f1=0.8)
    failed = dict(good, passed=False, missing=1, f1=0.9)
    improved = dict(good, f1=0.9)
    assert training_entry.physical_rank([good, good]) < training_entry.physical_rank([improved, failed])


def test_step_balanced_cycle_repeats_short_tasks(plan_path):
    short = PianoResidualEnv(plan_path, PACKAGE)
    long = PianoResidualEnv(
        PACKAGE / "examples/two_tigers_flat_palms/verified_40/performance.yaml", PACKAGE)
    cycle = PianoTaskCycle([short, long], balance="step")
    try:
        cycle._next_cycle()
        counts = np.bincount(cycle.order, minlength=2)
        assert counts[0] == np.ceil(cycle.episode_lengths.max() / cycle.episode_lengths[0])
        assert counts[1] == 1
        with pytest.raises(ValueError):
            PianoTaskCycle([short], balance="unknown")
    finally:
        cycle.close()


def test_observation_contains_forearm_position_and_active_finger(plan_path):
    env = PianoResidualEnv(plan_path, PACKAGE)
    try:
        obs, _ = env.reset(seed=0)
        forearm_offset = 42 + 14 + 20
        finger_offset = forearm_offset + 3 + 88 * 5
        assert np.any(obs[forearm_offset:forearm_offset + 3])
        assert not obs[finger_offset:finger_offset + 5].any()
        while env.runner.data.time < 0.22:
            env.step(np.zeros(20, np.float32))
        obs = env._observation()
        assert obs[finger_offset + 1] == 1.0
        assert obs.shape == (1337,)
    finally:
        env.close()
