"""Per-note fingering events and the MuJoCo performance-plan schema.

The planner writes `piano_performance/1` YAML; `run_performance.py` validates
and plays it.  Times in a plan are score seconds at tempo 1.0; the executor
multiplies them by `metadata.tempo_scale`.  `events.start_sec/end_sec` are the
intended physical key edges, while `hand_states.time_sec` are command times
(already backed off by the plan's press/release leads).
"""

import math
from pathlib import Path

import yaml

FINGERS = ("thumb", "index", "middle", "ring", "little")
HANDS = ("left", "right")
MAX_CHORD = 5
EPS = 1e-6


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _nonnegative(value, name):
    number = _finite(value, name)
    if number < 0:
        raise ValueError(f"{name} must not be negative")
    return number


def _values(value, count, name, low=None, high=None):
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise ValueError(f"{name} must contain exactly {count} values")
    result = []
    for index, item in enumerate(value):
        number = _finite(item, f"{name}[{index}]")
        if low is not None and number < low:
            raise ValueError(f"{name}[{index}] must be at least {low}")
        if high is not None and number > high:
            raise ValueError(f"{name}[{index}] must be at most {high}")
        result.append(number)
    return result


def _hand(value, name):
    if value not in HANDS:
        raise ValueError(f"{name} must be left or right")
    return value


def _finger(value, name):
    if value not in FINGERS:
        raise ValueError(f"{name} must be one of {FINGERS}")
    return value


def load_events(path):
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_events(document, path)
    return document


def validate_events(document, path="<events>"):
    if not isinstance(document, dict):
        raise ValueError(f"{path}: event document must be a mapping")
    if document.get("format") != "piano_fingering/1":
        raise ValueError(f"{path}: format must be piano_fingering/1")
    events = document.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError(f"{path}: events must be a non-empty list")
    seen_ids = set()
    seen_keys = set()
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"{path}: event {index} must be a mapping")
        event_id = event.get("id")
        if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id <= 0:
            raise ValueError(f"{path}: event {index} id must be a positive integer")
        if event_id in seen_ids:
            raise ValueError(f"{path}: duplicate event id {event_id}")
        seen_ids.add(event_id)
        hand = event.get("hand")
        if hand is not None:
            _hand(hand, f"{path}: event {event_id} hand")
        start = _nonnegative(event.get("start"), f"{path}: event {event_id} start")
        end = _nonnegative(event.get("end"), f"{path}: event {event_id} end")
        if end <= start:
            raise ValueError(f"{path}: event {event_id} end must be after start")
        note = event.get("note")
        if not isinstance(note, int) or isinstance(note, bool) or not 21 <= note <= 108:
            raise ValueError(f"{path}: event {event_id} note must be 21-108")
        velocity = event.get("velocity")
        if not isinstance(velocity, int) or isinstance(velocity, bool) or not 0 <= velocity <= 127:
            raise ValueError(f"{path}: event {event_id} velocity must be 0-127")
        finger = event.get("finger")
        if finger is not None:
            _finger(finger, f"{path}: event {event_id} finger")
        key = (hand, note, round(start, 9))
        if key in seen_keys:
            raise ValueError(f"{path}: duplicate hand/note/start {key}")
        seen_keys.add(key)
    return document


def events_by_hand(events, left_max_note=59):
    """Assign unlabeled notes by pitch and return one sorted list per hand."""
    by_hand = {"left": [], "right": []}
    for event in events:
        hand = event.get("hand")
        if hand is None:
            hand = "left" if event["note"] <= left_max_note else "right"
        by_hand[hand].append(event)
    for side in HANDS:
        by_hand[side].sort(key=lambda item: (item["start"], item["note"], item["id"]))
    return by_hand


def group_events(events, chord_epsilon=1e-3):
    """Group one hand's events by onset; a group's end is its latest release."""
    ordered = sorted(events, key=lambda item: (item["start"], item["note"], item["id"]))
    groups = []
    for event in ordered:
        if groups and event["start"] - groups[-1]["start"] <= chord_epsilon:
            group = groups[-1]
            group["notes"].append(event)
            group["end"] = max(group["end"], event["end"])
        else:
            groups.append({"start": event["start"], "end": event["end"], "notes": [event]})
    return groups


def maximum_live_keys(events):
    edges = []
    for event in events:
        start = event.get("start", event.get("start_sec"))
        end = event.get("end", event.get("end_sec"))
        if start is None or end is None:
            raise ValueError("event is missing start/end or start_sec/end_sec")
        edges.append((start, 1))
        edges.append((end, -1))
    live = 0
    peak = 0
    for _, delta in sorted(edges, key=lambda item: (item[0], item[1])):
        live += delta
        peak = max(peak, live)
    return peak


def load_plan(path):
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_plan(document, path)
    return document


def validate_physical_key_spans(spans, path):
    """Reject overlapping requests for a single passive key."""
    last_by_note = {}
    for start, end, note in sorted(spans):
        if start < last_by_note.get(note, 0.0) - EPS:
            raise ValueError(f"{path}: overlapping events on physical key {note}")
        last_by_note[note] = end


def validate_plan(document, path="<plan>"):
    if not isinstance(document, dict):
        raise ValueError(f"{path}: plan must be a mapping")
    if document.get("format") != "piano_performance/1":
        raise ValueError(f"{path}: format must be piano_performance/1")
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError(f"{path}: metadata must be a mapping")
    tempo = _finite(metadata.get("tempo_scale", 1.0), f"{path}: metadata.tempo_scale")
    if tempo <= 0:
        raise ValueError(f"{path}: metadata.tempo_scale must be positive")
    for name in ("start_padding_sec", "arm_lead_sec", "press_lead_sec",
                 "release_lead_sec", "hand_transition_sec", "timing_tolerance_sec"):
        if name in metadata:
            _nonnegative(metadata[name], f"{path}: metadata.{name}")
    hands = document.get("hands")
    if not isinstance(hands, dict) or not hands:
        raise ValueError(f"{path}: hands must be a non-empty mapping")
    for side, hand in hands.items():
        _hand(side, f"{path}: hand key")
        if not isinstance(hand, dict):
            raise ValueError(f"{path}: hands.{side} must be a mapping")
        _validate_hand(side, hand, path)
    if len(hands) > 1:
        validate_physical_key_spans(
            ((event["start_sec"], event["end_sec"], event["note"])
             for hand in hands.values() for event in hand["events"]), path)
    return document


def _validate_hand(side, hand, path):
    ready = _values(hand.get("ready_state"), 20, f"{path}: {side}.ready_state", 0.0, 255.0)
    del ready
    _values(hand.get("arm_start"), 7, f"{path}: {side}.arm_start")

    waypoints = hand.get("arm_waypoints")
    if not isinstance(waypoints, list):
        raise ValueError(f"{path}: {side}.arm_waypoints must be a list")
    previous_time = None
    for index, waypoint in enumerate(waypoints):
        if not isinstance(waypoint, dict):
            raise ValueError(f"{path}: {side}.arm_waypoints[{index}] must be a mapping")
        time_sec = _nonnegative(waypoint.get("time_sec"),
                                f"{path}: {side}.arm_waypoints[{index}].time_sec")
        move_after = _nonnegative(waypoint.get("move_after_sec"),
                                  f"{path}: {side}.arm_waypoints[{index}].move_after_sec")
        if move_after > time_sec + EPS:
            raise ValueError(
                f"{path}: {side}.arm_waypoints[{index}] move_after_sec is after time_sec")
        _values(waypoint.get("joints"), 7, f"{path}: {side}.arm_waypoints[{index}].joints")
        if previous_time is not None and time_sec <= previous_time + EPS:
            raise ValueError(f"{path}: {side}.arm_waypoints must have increasing times")
        previous_time = time_sec

    states = hand.get("hand_states")
    if not isinstance(states, list):
        raise ValueError(f"{path}: {side}.hand_states must be a list")
    previous_time = None
    for index, state in enumerate(states):
        if not isinstance(state, dict):
            raise ValueError(f"{path}: {side}.hand_states[{index}] must be a mapping")
        time_sec = _nonnegative(state.get("time_sec"),
                                f"{path}: {side}.hand_states[{index}].time_sec")
        pressed = state.get("pressed")
        if not isinstance(pressed, list) or len(pressed) > MAX_CHORD:
            raise ValueError(f"{path}: {side}.hand_states[{index}].pressed must be a list")
        for finger in pressed:
            _finger(finger, f"{path}: {side}.hand_states[{index}].pressed")
        if len(set(pressed)) != len(pressed):
            raise ValueError(f"{path}: {side}.hand_states[{index}].pressed repeats a finger")
        if "transition_sec" in state:
            _nonnegative(state["transition_sec"],
                         f"{path}: {side}.hand_states[{index}].transition_sec")
        _values(state.get("positions"), 20,
                f"{path}: {side}.hand_states[{index}].positions", 0.0, 255.0)
        if previous_time is not None and time_sec <= previous_time + EPS:
            raise ValueError(f"{path}: {side}.hand_states must have increasing times")
        previous_time = time_sec

    events = hand.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError(f"{path}: {side}.events must be a non-empty list")
    seen_ids = set()
    previous_start = None
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"{path}: {side}.events[{index}] must be a mapping")
        event_id = event.get("id")
        if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id <= 0:
            raise ValueError(f"{path}: {side}.events[{index}].id must be a positive integer")
        if event_id in seen_ids:
            raise ValueError(f"{path}: {side}.events repeats id {event_id}")
        seen_ids.add(event_id)
        start = _nonnegative(event.get("start_sec"), f"{path}: {side} event {event_id} start_sec")
        end = _nonnegative(event.get("end_sec"), f"{path}: {side} event {event_id} end_sec")
        if end <= start:
            raise ValueError(f"{path}: {side} event {event_id} end_sec must be after start_sec")
        note = event.get("note")
        if not isinstance(note, int) or isinstance(note, bool) or not 21 <= note <= 108:
            raise ValueError(f"{path}: {side} event {event_id} note must be 21-108")
        velocity = event.get("velocity", 0)
        if not isinstance(velocity, int) or isinstance(velocity, bool) or not 0 <= velocity <= 127:
            raise ValueError(f"{path}: {side} event {event_id} velocity must be 0-127")
        _finger(event.get("finger"), f"{path}: {side} event {event_id} finger")
        waypoint = event.get("arm_waypoint")
        if not isinstance(waypoint, int) or isinstance(waypoint, bool) or not 0 <= waypoint < len(waypoints):
            raise ValueError(f"{path}: {side} event {event_id} arm_waypoint is out of range")
        if previous_start is not None and start < previous_start - EPS:
            raise ValueError(f"{path}: {side}.events must be sorted by start_sec")
        previous_start = start

    _validate_same_finger(side, events, path)
    peak = maximum_live_keys(events)
    if peak > MAX_CHORD:
        raise ValueError(f"{path}: {side} hand has {peak} simultaneous notes; max is {MAX_CHORD}")
    _validate_arm_moves(side, events, waypoints, path)


def _validate_same_finger(side, events, path):
    by_finger = {}
    for event in events:
        by_finger.setdefault(event["finger"], []).append(event)
    for finger, finger_events in by_finger.items():
        finger_events.sort(key=lambda item: item["start_sec"])
        previous_end = None
        for event in finger_events:
            if previous_end is not None and event["start_sec"] < previous_end - EPS:
                raise ValueError(
                    f"{path}: {side} {finger} is reused before note {event['id']} "
                    "has been released")
            previous_end = event["end_sec"]


def _validate_arm_moves(side, events, waypoints, path):
    for index, waypoint in enumerate(waypoints):
        if index == 0:
            continue
        start = float(waypoint["move_after_sec"])
        end = float(waypoint["time_sec"])
        if end <= start + EPS:
            continue
        for event in events:
            if event["start_sec"] < end - EPS and event["end_sec"] > start + EPS:
                raise ValueError(
                    f"{path}: {side} arm move {index} ({start:.3f}-{end:.3f}s) overlaps "
                    f"held note {event['note']}")


def write_plan(path, plan):
    validate_plan(plan, str(path))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.safe_dump(plan, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return plan


def summarize_plan(plan):
    summary = {"tempo_scale": plan.get("metadata", {}).get("tempo_scale", 1.0), "hands": {}}
    for side, hand in plan["hands"].items():
        summary["hands"][side] = {
            "events": len(hand["events"]),
            "arm_waypoints": len(hand["arm_waypoints"]),
            "hand_states": len(hand["hand_states"]),
            "chords": sum(
                1 for index, event in enumerate(hand["events"])
                if any(other["start_sec"] == event["start_sec"] and other["id"] != event["id"]
                       for other in hand["events"])),
            "fingers": sorted({event["finger"] for event in hand["events"]}),
            "last_end_sec": max(event["end_sec"] for event in hand["events"]),
        }
    return summary
