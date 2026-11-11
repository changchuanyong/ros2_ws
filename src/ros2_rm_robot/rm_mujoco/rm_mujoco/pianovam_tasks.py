"""PianoVAM-driven RL task schema and window extraction.

Tasks keep the original absolute PianoVAM note times.  The runtime uses
``origin_sec`` plus relative frame times; missing hand/finger labels are marked,
never fabricated.
"""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .keyboard import KEY_NOTES
from .performance import FINGERS

FORMAT = "piano_rl_tasks/1"
SPLITS = ("train", "ext-train", "valid", "test")
HAND_ORDER = ("left", "right")
FINGER_HINT_IDLE = -1
FINGER_HINT_UNKNOWN = -2
LOOKAHEAD_SEC = (0.0, 0.05, 0.10, 0.20, 0.40)
TAIL_SEC = 0.6


class NoTaskWindows(ValueError):
    """The requested source has no window with the given boundaries."""


@dataclass(frozen=True)
class TaskEvent:
    id: int
    hand: str
    note: int
    start_sec: float
    end_sec: float
    velocity: int
    finger: str | None
    finger_source: str
    hand_source: str

    def relative(self, origin_sec):
        return {
            "id": self.id, "side": self.hand, "note": self.note,
            "on": self.start_sec - origin_sec,
            "off": self.end_sec - origin_sec,
            "finger": self.finger, "prior_finger": self.finger,
        }


@dataclass(frozen=True)
class PianoVamTask:
    id: str
    origin_sec: float
    duration_sec: float
    events: tuple[TaskEvent, ...]
    frame_time_sec: np.ndarray
    target_keys: np.ndarray
    finger_hints: np.ndarray

    @property
    def event_views(self):
        return [event.relative(self.origin_sec) for event in self.events]

    @property
    def unlabeled_fingers(self):
        return sum(event.finger is None for event in self.events)


@dataclass(frozen=True)
class PianoVamTaskSet:
    source: str
    source_sha256: str
    split: str
    left_max_note: int
    frame_dt: float
    lookahead_sec: tuple[float, ...]
    tasks: tuple[PianoVamTask, ...]

    @property
    def task_count(self):
        return len(self.tasks)


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive(value, name):
    number = _finite(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _integer(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if low is not None and value < low:
        raise ValueError(f"{name} must be at least {low}")
    if high is not None and value > high:
        raise ValueError(f"{name} must be at most {high}")
    return value


def _finger_hints(events, time_sec, origin_sec):
    row = np.full(10, FINGER_HINT_IDLE, dtype=np.int8)
    for hand_index, side in enumerate(HAND_ORDER):
        active = [event for event in events
                  if event.hand == side
                  and event.start_sec <= origin_sec + time_sec < event.end_sec]
        if not active:
            continue
        base = hand_index * 5
        if any(event.finger is None for event in active):
            row[base:base + 5] = FINGER_HINT_UNKNOWN
            continue
        for event in active:
            row[base + FINGERS.index(event.finger)] = FINGERS.index(event.finger)
    return row


def _targets(events, time_sec, origin_sec):
    target = np.zeros(88, dtype=np.int8)
    for event in events:
        if event.start_sec <= origin_sec + time_sec < event.end_sec:
            target[event.note - 21] = 1
    return target


def _validate_frames(task_id, time_sec, targets, hints, events, origin, duration):
    if not isinstance(time_sec, (list, tuple)) or len(time_sec) < 2:
        raise ValueError(f"{task_id}: frames.time_sec must contain at least two values")
    times = np.asarray([_finite(value, f"{task_id} frame time") for value in time_sec])
    if times[0] != 0.0 or np.any(np.diff(times) <= 0):
        raise ValueError(f"{task_id}: frame times must start at 0 and increase")
    if times[-1] > duration + 1e-9 or times[-1] < duration - 1e-9:
        raise ValueError(f"{task_id}: last frame must equal duration")
    targets = np.asarray(targets, dtype=np.int8)
    hints = np.asarray(hints, dtype=np.int8)
    if targets.shape != (len(times), 88):
        raise ValueError(f"{task_id}: target_keys must be (frames, 88)")
    if hints.shape != (len(times), 10):
        raise ValueError(f"{task_id}: finger_hints must be (frames, 10)")
    if not np.isin(targets, (0, 1)).all():
        raise ValueError(f"{task_id}: target_keys must be 0/1")
    if not np.isin(hints, tuple(range(-2, 5))).all():
        raise ValueError(f"{task_id}: finger_hints must be -2..4")
    for index, time_sec in enumerate(times):
        expected_target = _targets(events, float(time_sec), origin)
        expected_hints = _finger_hints(events, float(time_sec), origin)
        if not np.array_equal(targets[index], expected_target):
            raise ValueError(f"{task_id}: target_keys disagree with events at frame {index}")
        if not np.array_equal(hints[index], expected_hints):
            raise ValueError(f"{task_id}: finger_hints disagree with events at frame {index}")
    return times, targets, hints


def _parse_event(document, task_id, origin, duration, seen):
    event_id = _integer(document.get("id"), f"{task_id} event id", 1)
    if event_id in seen:
        raise ValueError(f"{task_id}: duplicate event id {event_id}")
    seen.add(event_id)
    hand = document.get("hand")
    if hand not in HAND_ORDER:
        raise ValueError(f"{task_id}: event hand must be left or right")
    note = _integer(document.get("note"), f"{task_id} event note", 21, 108)
    start = _finite(document.get("start_sec"), f"{task_id} event start_sec")
    end = _finite(document.get("end_sec"), f"{task_id} event end_sec")
    if end <= start or end <= origin or end > origin + duration + 1e-9:
        raise ValueError(f"{task_id}: event end must be after start and inside duration")
    velocity = _integer(document.get("velocity"), f"{task_id} event velocity", 0, 127)
    finger = document.get("finger")
    if finger is not None and finger not in FINGERS:
        raise ValueError(f"{task_id}: event finger must be null or a finger name")
    finger_source = document.get("finger_source", "labeled" if finger else "unlabeled")
    hand_source = document.get("hand_source", "labeled")
    if finger_source not in ("labeled", "unlabeled"):
        raise ValueError(f"{task_id}: finger_source must be labeled or unlabeled")
    if hand_source not in ("labeled", "inferred"):
        raise ValueError(f"{task_id}: hand_source must be labeled or inferred")
    return TaskEvent(event_id, hand, note, start, end, velocity, finger,
                     finger_source, hand_source)


def _parse_task(document, frame_dt, index):
    if not isinstance(document, dict):
        raise ValueError(f"task {index} must be a mapping")
    task_id = document.get("id")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError(f"task {index} id must be a non-empty string")
    origin = _finite(document.get("origin_sec"), f"{task_id} origin_sec")
    duration = _positive(document.get("duration_sec"), f"{task_id} duration_sec")
    events_document = document.get("events")
    if not isinstance(events_document, list) or not events_document:
        raise ValueError(f"{task_id}: events must be a non-empty list")
    seen = set()
    events = tuple(_parse_event(item, task_id, origin, duration, seen)
                   for item in events_document)
    frames = document.get("frames")
    if not isinstance(frames, dict):
        raise ValueError(f"{task_id}: frames must be a mapping")
    times, targets, hints = _validate_frames(
        task_id, frames.get("time_sec"), frames.get("target_keys"),
        frames.get("finger_hints"), events, origin, duration)
    return PianoVamTask(task_id, origin, duration, events, times, targets, hints)


def task_set_from_dict(document):
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError(f"expected {FORMAT}")
    source = document.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError("source must be a non-empty string")
    source_sha = document.get("source_sha256")
    if not isinstance(source_sha, str) or len(source_sha) != 64:
        raise ValueError("source_sha256 must be a 64-character hex digest")
    split = document.get("split")
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    left_max_note = _integer(document.get("left_max_note"), "left_max_note", 0, 108)
    frame_dt = _positive(document.get("frame_dt"), "frame_dt")
    lookahead = document.get("lookahead_sec", list(LOOKAHEAD_SEC))
    if not isinstance(lookahead, (list, tuple)) or not lookahead:
        raise ValueError("lookahead_sec must be a non-empty list")
    lookahead = tuple(_finite(value, "lookahead_sec") for value in lookahead)
    if lookahead[0] != 0.0 or any(b <= a for a, b in zip(lookahead, lookahead[1:])):
        raise ValueError("lookahead_sec must start at 0 and increase")
    tasks_document = document.get("tasks")
    if not isinstance(tasks_document, list):
        raise ValueError("tasks must be a list")
    tasks = tuple(_parse_task(item, frame_dt, index)
                  for index, item in enumerate(tasks_document))
    return PianoVamTaskSet(source, source_sha, split, left_max_note,
                           frame_dt, lookahead, tasks)


def load_task_set(path):
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read task file {path}: {error}") from None
    return task_set_from_dict(document)


def _normalise_events(events, left_max_note):
    normalised = []
    seen = set()
    for event in events:
        note = _integer(event.get("note"), "note", 21, 108)
        start = _finite(event.get("start"), "start")
        end = _finite(event.get("end"), "end")
        if start < 0 or end <= start:
            raise ValueError("event times must satisfy 0 <= start < end")
        hand = event.get("hand")
        if hand in (None, ""):
            hand = "left" if note <= left_max_note else "right"
            hand_source = "inferred"
        elif hand in HAND_ORDER:
            hand_source = "labeled"
        else:
            raise ValueError("event hand must be left, right or null")
        finger = event.get("finger")
        if finger is not None and finger not in FINGERS:
            raise ValueError("event finger must be null or a finger name")
        event_id = _integer(event.get("id"), "event id", 1)
        if event_id in seen:
            raise ValueError(f"duplicate event id {event_id}")
        seen.add(event_id)
        normalised.append(TaskEvent(
            event_id, hand, note, start, end,
            _integer(event.get("velocity"), "velocity", 0, 127), finger,
            "labeled" if finger else "unlabeled", hand_source))
    normalised.sort(key=lambda item: (item.start_sec, HAND_ORDER.index(item.hand),
                                      item.note, item.id))
    if not normalised:
        raise ValueError("no events")
    return normalised


def _onset_groups(events):
    groups = []
    for event in events:
        if not groups or abs(event.start_sec - groups[-1][0].start_sec) > 1e-9:
            groups.append([event])
        else:
            groups[-1].append(event)
    return groups


def _frame_times(duration, frame_dt):
    times = np.arange(0.0, duration + 1e-9, frame_dt)
    if len(times) < 2:
        times = np.array([0.0, duration], dtype=float)
    elif times[-1] < duration - 1e-9:
        times = np.append(times, duration)
    return times


def extract_tasks(events, *, source, split, left_max_note=59,
                  window_notes=1, stride_sec=0.0, tail_sec=TAIL_SEC,
                  lead_in_sec=0.0, frame_dt=0.02, allow_carry_in=False,
                  max_tasks=0, lookahead_sec=LOOKAHEAD_SEC, complete_phrases=False):
    """Build task windows from absolute PianoVAM events without a planner."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    if complete_phrases and allow_carry_in:
        raise ValueError("complete phrases require a silent start")
    window_notes = _integer(window_notes, "window_notes", 1)
    max_tasks = _integer(max_tasks, "max_tasks", 0)
    stride_sec = _finite(stride_sec, "stride_sec")
    if stride_sec < 0:
        raise ValueError("stride_sec must not be negative")
    tail_sec = _finite(tail_sec, "tail_sec")
    if tail_sec < 0:
        raise ValueError("tail_sec must not be negative")
    lead_in_sec = _finite(lead_in_sec, "lead_in_sec")
    if lead_in_sec < 0:
        raise ValueError("lead_in_sec must not be negative")
    frame_dt = _positive(frame_dt, "frame_dt")
    normalised = _normalise_events(events, left_max_note)
    groups = _onset_groups(normalised)
    latest_ends = [0.0]
    for group in groups:
        latest_ends.append(max(latest_ends[-1], max(event.end_sec for event in group)))
    tasks = []
    last_origin = -math.inf
    for start_index in range(len(groups)):
        first_on = groups[start_index][0].start_sec
        origin = max(0.0, first_on - lead_in_sec)
        end_index = min(start_index + window_notes, len(groups))
        if complete_phrases:
            previous_end = latest_ends[start_index]
            if previous_end > first_on:
                continue
            # Padding is available only after the preceding notes release.
            origin = max(origin, previous_end)
        if origin - last_origin < stride_sec - 1e-9:
            continue
        selected = [event for group in groups[start_index:end_index]
                    for event in group]
        if complete_phrases:
            if (end_index < len(groups)
                    and groups[end_index][0].start_sec < latest_ends[end_index]):
                continue
        elif latest_ends[start_index] > origin:
            if not allow_carry_in:
                continue
            # Include notes that start inside the preparation interval too.
            carry_in = [event for group in groups[:start_index] for event in group
                        if event.end_sec > origin]
            selected = carry_in + selected
        duration = max(event.end_sec for event in selected) - origin + tail_sec
        times = _frame_times(duration, frame_dt)
        targets = np.stack([_targets(selected, float(time), origin) for time in times])
        hints = np.stack([_finger_hints(selected, float(time), origin) for time in times])
        task_id = f"{Path(source).stem}:{origin:.6f}:{len(selected)}"
        tasks.append(PianoVamTask(
            task_id, origin, float(duration), tuple(selected), times,
            targets.astype(np.int8), hints.astype(np.int8)))
        last_origin = origin
        if max_tasks and len(tasks) >= max_tasks:
            break
    if not tasks:
        raise NoTaskWindows("no task windows satisfy the requested boundaries")
    return tuple(tasks)


def build_task_set(events, *, source, split, source_sha256=None,
                   left_max_note=59, window_notes=1, stride_sec=0.0,
                   tail_sec=TAIL_SEC, lead_in_sec=0.0, frame_dt=0.02,
                   allow_carry_in=False, max_tasks=0,
                   lookahead_sec=LOOKAHEAD_SEC, complete_phrases=False):
    source_path = Path(source)
    if source_sha256 is None:
        try:
            source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError:
            source_sha256 = hashlib.sha256(str(source).encode("utf-8")).hexdigest()
    tasks = extract_tasks(
        events, source=str(source), split=split, left_max_note=left_max_note,
        window_notes=window_notes, stride_sec=stride_sec, tail_sec=tail_sec,
        lead_in_sec=lead_in_sec, frame_dt=frame_dt,
        allow_carry_in=allow_carry_in, max_tasks=max_tasks,
        lookahead_sec=lookahead_sec, complete_phrases=complete_phrases)
    return PianoVamTaskSet(str(source), source_sha256, split, left_max_note,
                           frame_dt, tuple(lookahead_sec), tasks)


def task_set_to_dict(task_set):
    return {
        "format": FORMAT,
        "source": task_set.source,
        "source_sha256": task_set.source_sha256,
        "split": task_set.split,
        "left_max_note": task_set.left_max_note,
        "frame_dt": task_set.frame_dt,
        "lookahead_sec": list(task_set.lookahead_sec),
        "tasks": [{
            "id": task.id,
            "origin_sec": task.origin_sec,
            "duration_sec": task.duration_sec,
            "events": [{
                "id": event.id, "hand": event.hand, "note": event.note,
                "start_sec": event.start_sec, "end_sec": event.end_sec,
                "velocity": event.velocity, "finger": event.finger,
                "finger_source": event.finger_source,
                "hand_source": event.hand_source,
            } for event in task.events],
            "frames": {
                "time_sec": task.frame_time_sec.tolist(),
                "target_keys": task.target_keys.tolist(),
                "finger_hints": task.finger_hints.tolist(),
            },
        } for task in task_set.tasks],
    }


def write_task_set(path, task_set):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task_set_to_dict(task_set), indent=2) + "\n",
                    encoding="utf-8")
    return path


def summarize_task_set(task_set):
    return {
        "tasks": task_set.task_count,
        "events": sum(len(task.events) for task in task_set.tasks),
        "unlabeled_fingers": sum(task.unlabeled_fingers for task in task_set.tasks),
        "split": task_set.split,
        "frame_dt": task_set.frame_dt,
    }
