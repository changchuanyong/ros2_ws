"""Check the event and performance-plan contracts without MuJoCo."""

from pathlib import Path
import sys

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.performance import (  # noqa: E402
    events_by_hand, group_events, maximum_live_keys, validate_events, validate_plan,
)


def _event(event_id=1, hand="right", start=1.0, end=1.5, note=60, finger="thumb"):
    return {"id": event_id, "hand": hand, "start": start, "end": end,
            "note": note, "velocity": 80, "finger": finger}


def _hand(event=None):
    event = event or {"id": 1, "note": 60, "start_sec": 1.0, "end_sec": 1.5,
                      "velocity": 80, "finger": "thumb", "arm_waypoint": 1}
    return {
        "ready_state": [0.0] * 20,
        "arm_start": [0.0] * 7,
        "arm_waypoints": [
            {"time_sec": 0.0, "move_after_sec": 0.0, "joints": [0.0] * 7},
            {"time_sec": 1.0, "move_after_sec": 0.5, "joints": [0.1] * 7},
        ],
        "hand_states": [
            {"time_sec": 0.9, "pressed": ["thumb"],
             "positions": [10.0] + [0.0] * 19},
        ],
        "events": [event],
    }


def _plan(hand=None):
    return {
        "format": "piano_performance/1",
        "metadata": {
            "tempo_scale": 1.0,
            "start_padding_sec": 1.0,
            "arm_lead_sec": 0.1,
            "press_lead_sec": 0.05,
            "release_lead_sec": 0.04,
            "hand_transition_sec": 0.04,
            "timing_tolerance_sec": 0.03,
        },
        "hands": {"right": hand or _hand()},
    }


def test_valid_plan_is_accepted():
    assert validate_plan(_plan())["format"] == "piano_performance/1"


def test_two_hands_can_press_different_keys_at_the_same_time():
    plan = _plan()
    left = _hand()
    left["events"][0].update(id=2, note=48)
    plan["hands"]["left"] = left
    assert set(validate_plan(plan)["hands"]) == {"left", "right"}


def test_two_hands_cannot_hold_the_same_physical_key_concurrently():
    plan = _plan()
    left = _hand()
    left["events"][0]["id"] = 2
    plan["hands"]["left"] = left
    with pytest.raises(ValueError, match="overlapping events on physical key 60"):
        validate_plan(plan)


def test_arm_move_over_a_held_note_is_rejected():
    hand = _hand()
    hand["arm_waypoints"][1]["move_after_sec"] = 0.9
    hand["arm_waypoints"][1]["time_sec"] = 1.2
    with pytest.raises(ValueError, match="overlaps held note"):
        validate_plan(_plan(hand))


def test_same_finger_cannot_start_before_release():
    hand = _hand()
    hand["events"].append({"id": 2, "note": 64, "start_sec": 1.4, "end_sec": 2.0,
                           "velocity": 80, "finger": "thumb", "arm_waypoint": 1})
    with pytest.raises(ValueError, match="reused before"):
        validate_plan(_plan(hand))


def test_hand_state_must_have_twenty_values():
    hand = _hand()
    hand["hand_states"][0]["positions"] = [0.0] * 19
    with pytest.raises(ValueError, match="20 values"):
        validate_plan(_plan(hand))


def test_arm_waypoint_index_must_exist():
    hand = _hand()
    hand["events"][0]["arm_waypoint"] = 5
    with pytest.raises(ValueError, match="out of range"):
        validate_plan(_plan(hand))


def test_event_end_must_use_the_key_release():
    with pytest.raises(ValueError, match="after start"):
        validate_events({"format": "piano_fingering/1", "events": [_event(start=2.0, end=2.0)]})


def test_event_document_rejects_duplicate_keys():
    document = {"format": "piano_fingering/1",
                "events": [_event(), _event(event_id=2)]}
    with pytest.raises(ValueError, match="duplicate hand/note/start"):
        validate_events(document)


def test_group_events_merges_near_simultaneous_notes():
    events = [
        _event(event_id=1, start=1.0, end=1.5, note=60),
        _event(event_id=2, start=1.0005, end=1.6, note=64, finger="middle"),
        _event(event_id=3, start=2.0, end=2.4, note=67, finger="little"),
    ]
    groups = group_events(events)
    assert len(groups) == 2
    assert [event["note"] for event in groups[0]["notes"]] == [60, 64]
    assert groups[0]["end"] == pytest.approx(1.6)


def test_noinfo_events_are_assigned_by_pitch():
    events = [_event(hand=None, note=48), _event(event_id=2, hand=None, note=72)]
    by_hand = events_by_hand(events)
    assert [event["note"] for event in by_hand["left"]] == [48]
    assert [event["note"] for event in by_hand["right"]] == [72]


def test_maximum_live_keys_uses_release_before_press_at_a_boundary():
    events = [_event(event_id=1, start=1.0, end=2.0, note=60),
              _event(event_id=2, start=2.0, end=2.5, note=64, finger="index")]
    assert maximum_live_keys(events) == 1
