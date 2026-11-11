"""Physical reward scenarios for the reference-free direct piano env."""

from pathlib import Path
import sys

import numpy as np
import pytest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.piano_direct_reward import DirectReward, RewardWeights  # noqa: E402


def _events():
    return [{"id": 1, "side": "right", "note": 60, "on": 0.2, "off": 0.4}]


def _keys(**notes):
    values = np.zeros(88, dtype=float)
    for note, value in notes.items():
        values[int(str(note).replace("note", "", 1)) - 21] = value
    return values


def test_correct_press_and_release_is_positive():
    reward = DirectReward()
    reward.reset(_events())
    total, components, details = reward.step(
        time_sec=0.2, key_normalized=_keys(note60=1.0),
        finger_distances={60: 0.0})
    assert total > 0
    assert components["key"] > 0
    assert components["timing"] > 0
    assert details["press_count"] == 1
    total, components, details = reward.step(
        time_sec=0.4, key_normalized=_keys(), finger_distances={})
    assert components["timing"] > 0
    assert details["release_count"] == 1
    assert total > 0


def test_strict_timing_uses_thirty_millisecond_gate():
    exact = DirectReward()
    exact.reset(_events())
    exact.step(time_sec=0.2, key_normalized=_keys(note60=1.0))
    exact.step(time_sec=0.4, key_normalized=_keys())
    assert exact.strict_timing()

    late = DirectReward()
    late.reset(_events())
    late.step(time_sec=0.238, key_normalized=_keys(note60=1.0))
    late.step(time_sec=0.404, key_normalized=_keys())
    assert not late.strict_timing()


def test_late_press_loses_key_credit_and_timing():
    reward = DirectReward()
    reward.reset(_events())
    total, components, details = reward.step(
        time_sec=0.238, key_normalized=_keys(note60=1.0))
    assert components["key"] < 0
    assert components["timing"] < 0
    assert total < 0
    assert details["press_count"] == 1


def test_static_and_missing_are_negative():
    reward = DirectReward()
    reward.reset(_events())
    total, components, _ = reward.step(
        time_sec=0.2, key_normalized=_keys())
    assert components["key"] < 0
    assert components["finger"] == 0.0
    assert total < 0
    total, components, _ = reward.step(
        time_sec=0.25, key_normalized=_keys())
    assert components["timing"] < 0
    assert total < 0


def test_wrong_key_is_negative_and_worse_than_correct():
    correct = DirectReward()
    correct.reset(_events())
    correct_total, _, _ = correct.step(
        time_sec=0.2, key_normalized=_keys(note60=1.0))

    wrong = DirectReward()
    wrong.reset(_events())
    wrong_total, components, _ = wrong.step(
        time_sec=0.2, key_normalized=_keys(note62=1.0))
    assert components["key"] < 0
    assert wrong_total < correct_total
    assert wrong_total < 0


def test_holding_after_release_is_penalized():
    reward = DirectReward()
    reward.reset(_events())
    reward.step(time_sec=0.2, key_normalized=_keys(note60=1.0))
    total, components, details = reward.step(
        time_sec=0.5, key_normalized=_keys(note60=1.0))
    assert components["key"] < 0
    assert components["timing"] < 0
    assert details["late_release_events"] == 1
    assert total < 0


def test_finger_distance_only_helps_while_key_sounds():
    near = DirectReward()
    near.reset(_events())
    near_total, near_components, _ = near.step(
        time_sec=0.2, key_normalized=_keys(note60=1.0),
        finger_distances={60: 0.0})
    far = DirectReward()
    far.reset(_events())
    far_total, far_components, _ = far.step(
        time_sec=0.2, key_normalized=_keys(note60=1.0),
        finger_distances={60: 0.2})
    assert near_components["finger"] > far_components["finger"]
    assert near_total > far_total

    idle = DirectReward()
    idle.reset(_events())
    _, idle_components, _ = idle.step(
        time_sec=0.2, key_normalized=_keys(), finger_distances={60: 0.0})
    assert idle_components["finger"] == 0.0


def test_action_energy_and_safety_penalize():
    base = DirectReward()
    base.reset(_events())
    base_total, _, _ = base.step(
        time_sec=0.2, key_normalized=_keys(note60=1.0),
        action=np.zeros(20), previous_action=np.zeros(20),
        energy=0.0, other_contacts=0, key_excess=0.0, arm_error=0.0)

    noisy = DirectReward()
    noisy.reset(_events())
    noisy_total, noisy_components, _ = noisy.step(
        time_sec=0.2, key_normalized=_keys(note60=1.0),
        action=np.ones(20), previous_action=np.zeros(20),
        energy=10.0, other_contacts=1, key_excess=0.02, arm_error=0.1)
    assert noisy_components["energy"] < 0
    assert noisy_components["action"] < 0
    assert noisy_components["safety"] < 0
    assert noisy_total < base_total


def test_invalid_weights_and_shapes_fail_closed():
    with pytest.raises(ValueError):
        RewardWeights.from_mapping({"unknown": 1.0})
    with pytest.raises(ValueError):
        RewardWeights.from_mapping({"key": -1.0})
    reward = DirectReward()
    reward.reset(_events())
    with pytest.raises(ValueError):
        reward.step(time_sec=0.2, key_normalized=np.zeros(87))
    with pytest.raises(ValueError):
        reward.step(time_sec=0.2, key_normalized=np.zeros(88),
                    action=np.zeros(19))


def test_timing_uses_physics_edges_including_early_release():
    reward = DirectReward()
    reward.reset(_events())
    _, _, details = reward.step(
        time_sec=0.2, key_normalized=_keys(note60=0.8),
        edges=[(0.19, "on", 60)])
    assert details["press_count"] == 1
    _, _, details = reward.step(
        time_sec=0.4, key_normalized=_keys(),
        edges=[(0.386, "off", 60)])
    assert details["release_count"] == 1
    assert reward.events[0]["release_error"] == pytest.approx(-0.014)
    assert reward.strict_timing()
