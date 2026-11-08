"""Score observed physical key edges independently of the simulation controller."""

import math
from numbers import Real

from rm_mujoco.performance import validate_events, validate_physical_key_spans, validate_plan


def _time(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return float(value)


def expected_from_plan(plan):
    """Use the plan's padded, tempo-scaled physical edges on the simulation clock."""
    validate_plan(plan)
    tempo = plan["metadata"].get("tempo_scale", 1.0)
    events = [{"plan_event_id": event["id"], "hand": side, "finger": event["finger"],
               "note": event["note"], "velocity": event.get("velocity", 0),
               "start": event["start_sec"] * tempo, "end": event["end_sec"] * tempo}
              for side, hand in plan["hands"].items() for event in hand["events"]]
    # Older plans guarantee unique IDs only within each hand.
    return [{"id": index, **event} for index, event in enumerate(events, 1)]


def _observed_spans(edges):
    """Keep open notes and report malformed transitions instead of inventing releases."""
    active, spans, anomalies = {}, [], []
    previous = 0.0
    for index, edge in enumerate(edges):
        if not isinstance(edge, (list, tuple)) or len(edge) != 3:
            raise ValueError(f"edge {index} must be [time_sec, on/off, note]")
        stamp, kind, note = edge
        stamp = _time(stamp, f"edge {index} time")
        if stamp < previous:
            raise ValueError(f"edge {index} is out of time order")
        previous = stamp
        if kind not in ("on", "off") or isinstance(note, bool) or not isinstance(note, int) \
                or not 21 <= note <= 108:
            raise ValueError(f"edge {index} has invalid type or piano note")
        if kind == "on":
            spans.append({"index": len(spans), "note": note, "start": stamp, "end": None})
            if note in active:
                anomalies.append({"edge": index, "note": note, "reason": "duplicate_on"})
            else:
                active[note] = spans[-1]
        elif note not in active:
            anomalies.append({"edge": index, "note": note, "reason": "orphan_off"})
        else:
            span = active.pop(note)
            span["end"] = stamp
            if stamp <= span["start"]:
                anomalies.append({"edge": index, "note": note, "reason": "zero_duration"})
    return spans, sorted(active), anomalies


def _match_pitch(expected, observed, window):
    """Maximize ordered matches inside the window, then minimize total onset error."""
    rows, cols = len(expected), len(observed)
    previous = [(0, 0.0)] * (cols + 1)
    actions = [bytearray(cols + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        current = [(0, 0.0)] * (cols + 1)
        for j in range(1, cols + 1):
            best, action = previous[j], 1
            if current[j - 1] > best:
                best, action = current[j - 1], 2
            error = abs(expected[i - 1]["start"] - observed[j - 1]["start"])
            if error <= window + 1e-9:
                count, cost = previous[j - 1]
                candidate = (count + 1, cost - error)
                if candidate > best:
                    best, action = candidate, 3
            current[j], actions[i][j] = best, action
        previous = current
    pairs = []
    i, j = rows, cols
    while i and j:
        action = actions[i][j]
        if action == 3:
            pairs.append((expected[i - 1], observed[j - 1]))
            i, j = i - 1, j - 1
        elif action == 1:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def evaluate_events(expected, edges, *, source, tolerance=0.03, match_window=0.15):
    """Evaluate note events; this score does not certify contact or robot safety."""
    if source not in ("simulation", "recorded", "synthetic"):
        raise ValueError("source must be simulation, recorded or synthetic")
    tolerance = _time(tolerance, "tolerance")
    match_window = _time(match_window, "match_window")
    if tolerance <= 0 or match_window < tolerance:
        raise ValueError("require 0 < tolerance <= match_window")
    validate_events({"format": "piano_fingering/1", "events": expected})
    validate_physical_key_spans(
        ((e["start"], e["end"], e["note"]) for e in expected), "expected")
    observed, active, anomalies = _observed_spans(edges)
    matched = []
    for note in sorted({event["note"] for event in expected}):
        targets = sorted((e for e in expected if e["note"] == note), key=lambda e: e["start"])
        actual = [e for e in observed if e["note"] == note]
        for target, event in _match_pitch(targets, actual, match_window):
            onset_error = event["start"] - target["start"]
            release_error = None if event["end"] is None else event["end"] - target["end"]
            reasons = []
            if abs(onset_error) > tolerance + 1e-9:
                reasons.append("onset_timing")
            if release_error is None:
                reasons.append("unreleased")
            elif abs(release_error) > tolerance + 1e-9:
                reasons.append("release_timing")
            matched.append({"id": target["id"], "hand": target.get("hand"), "note": note,
                            "plan_event_id": target.get("plan_event_id", target["id"]),
                            "observed_index": event["index"],
                            "expected_on": target["start"], "expected_off": target["end"],
                            "observed_on": event["start"], "observed_off": event["end"],
                            "onset_error_sec": onset_error, "release_error_sec": release_error,
                            "reasons": reasons})
    matched.sort(key=lambda event: (event["expected_on"], event["id"]))
    used_ids = {event["id"] for event in matched}
    used_observed = {event["observed_index"] for event in matched}
    missing = [{**event, "reason": "missing"} for event in expected if event["id"] not in used_ids]
    extra = [{**event, "reason": "extra"} for event in observed if event["index"] not in used_observed]
    correct = sum(not event["reasons"] for event in matched)
    precision = correct / len(observed) if observed else 0.0
    recall = correct / len(expected)
    onset = [abs(event["onset_error_sec"]) for event in matched]
    release = [abs(event["release_error_sec"]) for event in matched
               if event["release_error_sec"] is not None]
    return {
        "format": "piano_evaluation/1", "source": source,
        "timing_tolerance_sec": tolerance, "match_window_sec": match_window,
        "passed": correct == len(expected) and not extra and not active and not anomalies,
        "counts": {"expected": len(expected), "observed": len(observed),
                   "matched": len(matched), "correct": correct,
                   "missing": len(missing), "extra": len(extra)},
        "precision": precision, "recall": recall,
        "f1": 2 * correct / (len(expected) + len(observed)),
        "max_onset_error_sec": max(onset, default=None),
        "max_release_error_sec": max(release, default=None),
        "matched": matched, "missing": missing, "extra": extra,
        "active_keys_at_end": active, "edge_anomalies": anomalies,
    }
