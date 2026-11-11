"""MuJoCo smoke tests for the reference-free `PianoDirectEnv`."""

from pathlib import Path
import sys

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")
pytest.importorskip("gymnasium")
PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "scripts"))

from rm_mujoco.piano_direct import OBSERVATION_SIZE, PianoDirectEnv  # noqa: E402
from rm_mujoco.pianovam_corpus import PianoVamCorpus, RecordingTasks  # noqa: E402
from rm_mujoco.pianovam_tasks import build_task_set, load_task_set, write_task_set  # noqa: E402
from train_piano_direct import evaluate, summarize_by_piece  # noqa: E402


def _task_path(tmp_path, notes=(55,)):
    events = []
    for event_id, note in enumerate(notes, start=1):
        events.append({
            "id": event_id,
            "hand": "left" if note < 60 else "right",
            "note": note,
            "start": 1.0,
            "end": 1.5,
            "velocity": 80,
            "finger": "index" if note < 60 else "middle",
        })
    task_set = build_task_set(
        events, source="fixture.tsv", split="train", source_sha256="a" * 64)
    path = tmp_path / "tasks.json"
    write_task_set(path, task_set)
    return path


@pytest.fixture
def env(tmp_path):
    environment = PianoDirectEnv(
        _task_path(tmp_path), PACKAGE, active_hands=("left",))
    try:
        yield environment
    finally:
        environment.close()


def test_environment_api(env):
    check_env = pytest.importorskip(
        "stable_baselines3.common.env_checker").check_env
    check_env(env, warn=True, skip_render_check=True)


def test_reset_observation_and_fixed_arms(env):
    observation, info = env.reset(seed=0)
    assert observation.shape == (OBSERVATION_SIZE,)
    assert np.isfinite(observation).all()
    assert info["task"]
    assert env.hand_model.classify(env.data)[1] == set()
    for side in ("left", "right"):
        assert np.allclose(
            env.data.qpos[env.hand_model.arm_qpos[side]], env.home_q[side], atol=1e-9)
    assert not hasattr(env, "arm_tracks")
    assert not hasattr(env, "hand_tracks")
    assert not hasattr(env, "nominal_qpos")


def test_action_changes_hand_and_masks_other_side(env):
    env.reset(seed=0)
    initial = {
        side: env.data.qpos[env.hand_model.hand_qpos[side]].copy()
        for side in ("left", "right")}
    action = np.zeros(20, dtype=np.float32)
    action[:10] = 0.5
    observation, reward, terminated, truncated, info = env.step(action)
    assert observation.shape == (OBSERVATION_SIZE,)
    assert np.isfinite(observation).all()
    assert np.isfinite(reward)
    assert set(info["reward_components"]) == {
        "key", "finger", "timing", "energy", "action", "safety", "total"}
    assert not terminated
    assert float(np.max(np.abs(
        env.data.qpos[env.hand_model.hand_qpos["left"]] - initial["left"]))) > 1e-4
    assert np.array_equal(env.last_command["right"], env.neutral20["right"])
    assert not np.array_equal(env.last_command["left"], env.neutral20["left"])
    assert info["arm_error_rad"] < 0.05


def test_active_channel_mask_limits_commands(tmp_path):
    environment = PianoDirectEnv(
        _task_path(tmp_path), PACKAGE, active_hands=("left",),
        active_channels=(1,))
    try:
        environment.reset(seed=0)
        neutral = environment.neutral20["left"].copy()
        action = np.ones(20, dtype=np.float32)
        environment.step(action)
        changed = np.flatnonzero(
            np.abs(environment.last_command["left"] - neutral) > 1e-6)
        assert changed.tolist() == [1]
    finally:
        environment.close()


def test_bad_action_is_rejected(env):
    env.reset(seed=0)
    with pytest.raises(ValueError):
        env.step(np.zeros(19, dtype=np.float32))
    with pytest.raises(ValueError):
        env.step(np.full(20, np.nan, dtype=np.float32))


def test_initial_jitter_changes_only_active_hand_and_is_reproducible(tmp_path):
    environment = PianoDirectEnv(
        _task_path(tmp_path), PACKAGE, active_hands=("left",),
        active_channels=(1,), initial_jitter=1.0)
    try:
        first, _ = environment.reset(seed=7)
        repeated, _ = environment.reset(seed=7)
        changed, _ = environment.reset(seed=9)
        assert np.array_equal(first, repeated)
        assert not np.array_equal(first[:21], changed[:21])
        assert np.array_equal(first[68:89], changed[68:89])
    finally:
        environment.close()


def test_task_end_truncates(env):
    env.reset(seed=0)
    truncated = False
    for _ in range(200):
        _, _, terminated, truncated, info = env.step(np.zeros(20, dtype=np.float32))
        assert not terminated
        if truncated:
            break
    assert truncated
    assert info["time_sec"] >= env.end_time - 1e-6


def test_carry_in_task_is_rejected(tmp_path):
    events = [
        {"id": 1, "hand": "left", "note": 55, "start": 1.0, "end": 2.0,
         "velocity": 80, "finger": "index"},
        {"id": 2, "hand": "left", "note": 57, "start": 1.5, "end": 2.2,
         "velocity": 80, "finger": "middle"},
    ]
    task_set = build_task_set(
        events, source="carry.tsv", split="train", source_sha256="b" * 64,
        window_notes=1, allow_carry_in=True)
    path = tmp_path / "carry.json"
    write_task_set(path, task_set)
    environment = PianoDirectEnv(path, PACKAGE, task_index=1,
                                 active_hands=("left",))
    try:
        with pytest.raises(ValueError, match="carry-in"):
            environment.reset(seed=0)
    finally:
        environment.close()


def test_source_has_no_reference_runner():
    source = (PACKAGE / "rm_mujoco/piano_direct.py").read_text(encoding="utf-8")
    for forbidden in ("PlanRunner", "arm_tracks", "hand_tracks", "nominal_qpos"):
        assert forbidden not in source


def _two_recordings(tmp_path):
    a = load_task_set(_task_path(tmp_path, notes=(55,)))
    b = load_task_set(_task_path(tmp_path, notes=(58, 72)))
    return PianoVamCorpus((RecordingTasks("a", "A", "First", a),
                          RecordingTasks("b", "B", "Second", b)))


def test_corpus_samples_each_recording_on_one_simulator(tmp_path):
    environment = PianoDirectEnv(_two_recordings(tmp_path), PACKAGE)
    model = environment.model
    try:
        for _ in range(2):
            _, first = environment.reset()
            _, second = environment.reset()
            assert {first["recording"], second["recording"]} == {"a", "b"}
            assert environment.model is model
        _, pinned = environment.reset(seed=19, options={"task_index": 1})
        assert pinned["piece"] == "Second"
        assert environment.task_set.tasks[1] is environment.task
    finally:
        environment.close()


def test_one_policy_reports_each_piece_and_keeps_all_score_events(tmp_path):
    class IdlePolicy:
        def predict(self, observation, deterministic=True):
            assert observation.shape == (OBSERVATION_SIZE,)
            return np.zeros(20, dtype=np.float32), None

    rows = evaluate(IdlePolicy(), _two_recordings(tmp_path), PACKAGE,
                    task_index=0, hand="left", action_scale=8.0, channels=(1,),
                    reward_weights=None, observation_lead=0.0, episodes=2,
                    seed_start=100, all_tasks=True)
    first, second = summarize_by_piece(rows)
    assert [first["piece"], second["piece"]] == ["First", "Second"]
    assert first["coverage"]["nominal_band_events"] == 1
    assert second["coverage"]["score_events"] == 2
    assert second["coverage"]["active_hand_events"] == 1
    assert second["coverage"]["nominal_band_events"] == 0
    assert first["timed_note_f1"] == second["timed_note_f1"] == 0
