"""Judge reference-free episodes from their physical key edges."""

from collections import defaultdict
from dataclasses import dataclass
import math

from .performance_runtime import note_duration_tolerance

TIMING_TOLERANCE_SEC = 0.03
TIME_EPSILON = 1e-9


@dataclass(frozen=True)
class SingleNoteResult:
    success: bool
    note: int
    expected_on: float
    expected_off: float
    observed_on: float | None
    observed_off: float | None
    onset_error: float | None
    release_error: float | None
    reason: str


def evaluate_edges(task, edges, *, timestep, tolerance_sec=TIMING_TOLERANCE_SEC,
                   key_violations=(), other_contacts=(), terminated=False,
                   onset_contacts=None):
    """Match one closed key interval per score event and report safety failures."""
    expected = defaultdict(list)
    for event in sorted(task.events, key=lambda event: event.start_sec):
        expected[event.note].append((event.start_sec - task.origin_sec,
                                     event.end_sec - task.origin_sec))
    active = {}
    actual = defaultdict(list)
    extra = []
    for time, edge, note in edges:
        if not math.isfinite(time):
            extra.append({"note": note, "kind": "invalid edge time"})
        elif edge == "on" and note not in active:
            active[note] = time
        elif edge == "off" and note in active and time > active[note]:
            actual[note].append((active.pop(note), time))
        else:
            extra.append({"note": note, "kind": "invalid edge", "time": time})
    for note, time in active.items():
        extra.append({"note": note, "kind": "unreleased key", "observed_on": time})

    matched = []
    missing = []
    for note in sorted(expected.keys() | actual.keys()):
        targets, intervals = expected[note], actual[note]
        if len(targets) == len(intervals):
            pairs = list(zip(range(len(targets)), range(len(intervals))))
        else:
            # Preserve good matches in diagnostics even when a key is retriggered.
            candidates = sorted((abs(on - observed_on), i, j)
                                for i, (on, _) in enumerate(targets)
                                for j, (observed_on, _) in enumerate(intervals))
            pairs = []
            used_targets, used_intervals = set(), set()
            for _, i, j in candidates:
                if i not in used_targets and j not in used_intervals:
                    pairs.append((i, j))
                    used_targets.add(i)
                    used_intervals.add(j)
        for i, j in pairs:
            on, off = targets[i]
            observed_on, observed_off = intervals[j]
            duration = off - on
            onset_error = observed_on - on
            release_error = observed_off - off
            duration_error = release_error - onset_error
            duration_tolerance = note_duration_tolerance(duration, tolerance_sec, timestep)
            matched.append({
                "note": note, "expected_on": on, "expected_off": off,
                "observed_on": observed_on, "observed_off": observed_off,
                "onset_error": onset_error, "release_error": release_error,
                "duration_error": duration_error,
                "duration_tolerance_sec": duration_tolerance,
                "contacts": (onset_contacts or {}).get((observed_on, note), []),
                "timing_passed": (
                    abs(onset_error) <= tolerance_sec + TIME_EPSILON
                    and abs(release_error) <= tolerance_sec + TIME_EPSILON
                    and abs(duration_error) <= duration_tolerance + TIME_EPSILON),
            })
        for i in set(range(len(targets))) - {i for i, _ in pairs}:
            missing.append({"note": note, "expected_on": targets[i][0]})
        for j in set(range(len(intervals))) - {j for _, j in pairs}:
            extra.append({"note": note, "kind": "extra press", "observed_on": intervals[j][0]})
    overlaps = []
    for i, first in enumerate(matched):
        for second in matched[i + 1:]:
            if first["note"] == second["note"]:
                continue
            expected_overlap = (min(first["expected_off"], second["expected_off"])
                                - max(first["expected_on"], second["expected_on"]))
            if expected_overlap > TIME_EPSILON:
                observed_overlap = (min(first["observed_off"], second["observed_off"])
                                    - max(first["observed_on"], second["observed_on"]))
                overlaps.append({
                    "notes": [first["note"], second["note"]],
                    "expected_sec": expected_overlap,
                    "observed_sec": max(0.0, observed_overlap),
                })
    timed = sum(row["timing_passed"] for row in matched)
    return {
        "success": bool(task.events and timed == len(task.events)
                        and not (extra or missing or key_violations or other_contacts or terminated)
                        and all(row["observed_sec"] > TIME_EPSILON for row in overlaps)),
        "matched": matched, "missing": missing, "extra": extra, "overlaps": overlaps,
        "timed_notes": timed,
        "expected_notes": len(task.events), "observed_notes": sum(map(len, actual.values())),
        "key_violations": list(key_violations), "other_contacts": list(other_contacts),
        "terminated": bool(terminated),
    }


def single_note_success(task, edges, *, tolerance_sec=TIMING_TOLERANCE_SEC,
                        timestep=0.002,
                        key_violations=(), other_contacts=(),
                        terminated=False):
    """Judge one note from physical key edges, not from policy actions."""
    if len(task.events) != 1:
        raise ValueError("single_note_success requires exactly one task event")
    event = task.events[0]
    expected_on = event.start_sec - task.origin_sec
    expected_off = event.end_sec - task.origin_sec
    edges = tuple(edges)
    report = evaluate_edges(
        task, edges, timestep=timestep, tolerance_sec=tolerance_sec,
        key_violations=key_violations, other_contacts=other_contacts, terminated=terminated)
    match = next(iter(report["matched"]), {})
    observed_on = match.get("observed_on") if match else next(
        (time for time, kind, note in edges if note == event.note and kind == "on"), None)
    observed_off = match.get("observed_off") if match else next(
        (time for time, kind, note in reversed(edges)
         if note == event.note and kind == "off"), None)
    if key_violations:
        reason = "key violation"
    elif other_contacts:
        reason = "other contact"
    elif terminated:
        reason = "terminated"
    elif any(row["note"] != event.note for row in report["extra"]):
        reason = "other key edge"
    elif any(row["kind"] == "unreleased key" for row in report["extra"]):
        reason = "missing release"
    elif not match:
        reason = "missing press"
    elif report["extra"]:
        reason = "unexpected same-key edge"
    elif abs(match["onset_error"]) > tolerance_sec + TIME_EPSILON:
        reason = "onset outside tolerance"
    elif abs(match["release_error"]) > tolerance_sec + TIME_EPSILON:
        reason = "release outside tolerance"
    elif not match["timing_passed"]:
        reason = "duration outside tolerance"
    else:
        reason = "passed"
    return SingleNoteResult(
        report["success"], event.note, expected_on, expected_off,
        observed_on, observed_off,
        match.get("onset_error"), match.get("release_error"), reason)
