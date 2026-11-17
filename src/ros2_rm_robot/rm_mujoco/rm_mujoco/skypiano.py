"""SKY-Piano explorer samples to score events and metric motion priors.

The public explorer CSVs are 30 Hz, unlike the 120 Hz source referred to by
fingering.json. Marker positions are millimetres. Missing observations are
never silently made into demonstrations; imputed values have a separate mask.
This module produces human motion targets, not robot actuator commands.
"""

import csv
import hashlib
import json
from pathlib import Path
import struct

import numpy as np

from .performance import FINGERS, validate_events


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_motion(path):
    """Read paired XYZ columns, preserving blanks/NaNs and rejecting infinities."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if len(columns) != len(set(columns)):
            raise ValueError(f"{path}: duplicate columns")
        markers = [name[:-2] for name in columns if name.endswith("_x")]
        if not markers or any(f"{name}_{axis}" not in columns
                              for name in markers for axis in "xyz"):
            raise ValueError(f"{path}: expected complete marker_x/y/z columns")
        values = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}: malformed CSV row")
            values.append([[float(row[f"{name}_{axis}"] or "nan")
                            for axis in "xyz"] for name in markers])
    positions = np.asarray(values, dtype=float)
    if len(positions) < 2 or np.isinf(positions).any():
        raise ValueError(f"{path}: require at least two frames, no infinities")
    # A marker with a missing coordinate is wholly unavailable.
    positions[~np.isfinite(positions).all(axis=2)] = np.nan
    return markers, positions * 0.001


def keyboard_frame(markers, raw_m):
    """Build a right-handed, Z-up frame from stationary keyboard-end markers.

    Origin: A0 lateral centre on the white-key reference line. X points from
    low to high notes; Y points away from the player; Z points up. The case
    margin and primary-marker correction follow the upstream geometry, and
    are assumptions of this dataset, not a robot/physical-piano calibration.
    """
    medians = {}
    for name in ("LEnd1", "REnd1", "LEnd", "REnd"):
        if name not in markers:
            continue
        points = raw_m[:, markers.index(name)]
        valid = np.isfinite(points).all(axis=1)
        if valid.sum() >= max(2, len(points) // 2):
            median = np.median(points[valid], axis=0)
            if np.max(np.linalg.norm(points[valid] - median, axis=1)) > 0.005:
                raise ValueError(f"{name}: keyboard marker moves more than 5 mm")
            medians[name] = median
    if all(name in medians for name in ("LEnd1", "REnd1")):
        pair, correction = ("LEnd1", "REnd1"), 0.0
    elif all(name in medians for name in ("LEnd", "REnd")):
        pair, correction = ("LEnd", "REnd"), 0.078
    else:
        raise ValueError("insufficient observed keyboard-end markers")
    left, right = (medians[name] for name in pair)
    delta = right - left
    span = np.linalg.norm(delta)
    if not 1.1985 <= span <= 1.6 or abs(delta[2]) > 0.005:
        raise ValueError("keyboard marker span/level is inconsistent with millimetre input")
    x_axis = delta.copy()
    x_axis[2] = 0
    x_axis /= np.linalg.norm(x_axis)
    z_axis = np.array([0., 0., 1.])
    y_axis = np.cross(z_axis, x_axis)
    rotation = np.column_stack((x_axis, y_axis, z_axis))
    margin = (span - 1.1985) / 2
    origin = left + margin * x_axis + correction * y_axis
    origin[2] = (left[2] + right[2]) / 2
    return {"origin_capture_m": origin.tolist(),
            "capture_from_keyboard_rotation": rotation.tolist(),
            "end_markers": list(pair), "span_m": float(span),
            "assumed_symmetric_case_margin_m": float(margin),
            "primary_reference_correction_m": correction,
            "axes": ["low_to_high", "away_from_player", "up"]}


def to_keyboard(positions, frame):
    origin = np.asarray(frame["origin_capture_m"])
    rotation = np.asarray(frame["capture_from_keyboard_rotation"])
    return (positions - origin) @ rotation


def hand_features(markers, keyboard_m):
    """Return wrist, five tips and a marker-defined palm frame for each hand.

    Palm X runs little-MCP to index-MCP; Y runs wrist to MCP centre,
    orthogonalized to X; Z = X cross Y. This is a human marker frame, not
    the L20 flange frame. Every output has a finite/observed validity mask.
    """
    features = {}
    for side, prefix in (("left", "L"), ("right", "R")):
        required = [prefix + suffix for suffix in
                    ("Wrist", "TF", "IF", "MF", "RF", "LF", "IM", "LM")]
        if any(name not in markers for name in required):
            raise ValueError(f"missing {side} wrist, tip or MCP markers")
        points = keyboard_m[:, [markers.index(name) for name in required]]
        wrist, tips = points[:, 0], points[:, 1:6]
        x_axis = points[:, 6] - points[:, 7]
        y_axis = (points[:, 6] + points[:, 7]) / 2 - wrist
        with np.errstate(invalid="ignore", divide="ignore"):
            x_axis /= np.linalg.norm(x_axis, axis=1, keepdims=True)
            y_axis -= np.sum(y_axis * x_axis, axis=1, keepdims=True) * x_axis
            y_axis /= np.linalg.norm(y_axis, axis=1, keepdims=True)
        rotation = np.stack((x_axis, y_axis, np.cross(x_axis, y_axis)), axis=2)
        features[f"{side}_wrist_m"] = wrist
        features[f"{side}_tips_m"] = tips
        features[f"{side}_palm_rotation"] = rotation
        features[f"{side}_palm_valid"] = np.isfinite(rotation).all(axis=(1, 2))
    return features


def read_events(csv_path, midi_notes, details_path=None):
    """Join pseudo-fingering one-to-one to MIDI, retaining exact MIDI edges.

    Explorer CSV edges are rounded to four decimals. Matching tolerance is
    0.06 ms, not an onset acceptance tolerance. Unknown hand/finger labels
    stay unknown even if finger_name contains a suggested candidate.
    """
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"onset", "offset", "pitch", "hand", "finger"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("fingering CSV is missing required columns")
        rows = list(reader)
    if len(rows) != len(midi_notes):
        raise ValueError("MIDI/fingering note counts differ")
    details = None
    if details_path is not None:
        details = json.loads(Path(details_path).read_text(encoding="utf-8-sig"))
        if len(details["fingering"]) != len(rows):
            raise ValueError("fingering detail count differs from CSV")
    unused = set(range(len(midi_notes)))
    unused_details = set(range(len(rows)))
    events, labels = [], []
    for index, row in enumerate(rows, 1):
        start, end, pitch = float(row["onset"]), float(row["offset"]), int(row["pitch"])
        candidates = [i for i in unused if midi_notes[i].note == pitch
                      and abs(midi_notes[i].start - start) <= 0.00006
                      and abs(midi_notes[i].end - end) <= 0.00006]
        if len(candidates) != 1:
            raise ValueError(f"row {index}: MIDI match is missing or ambiguous")
        match = candidates[0]
        unused.remove(match)
        note = midi_notes[match]
        hand = {"L": "left", "R": "right", "": None}.get(row["hand"], "invalid")
        finger = int(row["finger"]) if row["finger"] else None
        if hand == "invalid" or (hand is None) != (finger is None) \
                or (finger is not None and finger not in range(1, 6)):
            raise ValueError(f"row {index}: inconsistent hand/finger")
        label = {"id": index, "source": "pseudo_fingering",
                 "status": "labeled" if hand else "unknown",
                 "confidence": None, "tier": row.get("tier"),
                 "ambiguity": row.get("ambiguity"), "source_row": index + 1}
        if details is not None:
            matches = [i for i in unused_details
                       if details["fingering"][i]["pitch"] == pitch
                       and abs(details["fingering"][i]["onset"] - start) <= 0.00006
                       and abs(details["fingering"][i]["offset"] - end) <= 0.00006]
            if len(matches) != 1:
                raise ValueError(f"row {index}: detail match is missing or ambiguous")
            detail = details["fingering"][matches[0]]
            unused_details.remove(matches[0])
            detail_hand = {"Left": "left", "Right": "right", None: None}.get(
                detail.get("hand"), "invalid")
            if detail_hand != hand or detail.get("finger") != finger:
                raise ValueError(f"row {index}: CSV/detail label disagreement")
            label.update(status=detail["status"], confidence=detail.get("score"),
                         candidates=detail.get("candidates", []))
        elif row.get("confidence"):
            label["confidence"] = float(row["confidence"])
        confidence = label["confidence"]
        if confidence is not None and (not np.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError(f"row {index}: confidence outside [0, 1]")
        events.append({"id": index, "hand": hand, "finger": FINGERS[finger - 1] if finger else None,
                       "note": note.note, "velocity": note.velocity,
                       "start": note.start, "end": note.end})
        labels.append(label)
    document = {"format": "piano_fingering/1", "source": str(csv_path), "events": events}
    validate_events(document)
    return document, labels


def note_windows(events, labels, times, markers, observed, lead=0.2, tail=0.2):
    """List full note windows with context; never erase concurrent held notes."""
    if not np.isfinite([lead, tail]).all() or min(lead, tail) < 0:
        raise ValueError("lead/tail must be finite and nonnegative")
    by_id = {label["id"]: label for label in labels}
    windows = []
    for event in events:
        side, finger = event["hand"], event["finger"]
        if side is None or finger is None:
            continue
        start, end = event["start"] - lead, event["end"] + tail
        if start < times[0] or end > times[-1]:
            continue
        indices = np.flatnonzero((times >= start) & (times <= end))
        if len(indices) < 2:
            continue
        prefix = "L" if side == "left" else "R"
        tip = prefix + ("TF", "IF", "MF", "RF", "LF")[FINGERS.index(finger)]
        needed = [markers.index(prefix + suffix) for suffix in ("Wrist", "IM", "LM")]
        needed.append(markers.index(tip))
        valid = observed[np.ix_(indices, needed)].all(axis=1)
        context = [other["id"] for other in events if other["start"] < end
                   and other["end"] > start and other["id"] != event["id"]]
        same_hand = [other for other in events if other["id"] in context
                     and other["hand"] in (side, None)]
        windows.append({"event_id": event["id"], "side": side, "finger": finger,
                        "start_sec": start, "end_sec": end,
                        "frame_start": int(indices[0]), "frame_stop": int(indices[-1] + 1),
                        "context_event_ids": context,
                        "isolated_in_hand": not same_hand,
                        "observed_fraction": float(valid.mean()),
                        "label_confidence": by_id[event["id"]]["confidence"],
                        "robot_expert_eligible": False})
    return windows


def transform_targets(features, world_from_keyboard):
    """Apply an explicitly supplied rigid calibration; do not infer robot IK."""
    transform = np.asarray(world_from_keyboard, dtype=float)
    if transform.shape != (4, 4) or not np.isfinite(transform).all() \
            or not np.allclose(transform[3], [0, 0, 0, 1]):
        raise ValueError("world_from_keyboard must be a finite homogeneous 4x4 matrix")
    rotation, translation = transform[:3, :3], transform[:3, 3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6) \
            or not np.isclose(np.linalg.det(rotation), 1, atol=1e-6):
        raise ValueError("calibration must be rigid, without reflection or scaling")
    result = {}
    for name, values in features.items():
        if name.endswith("_m"):
            result[name] = values @ rotation.T + translation
        elif name.endswith("_rotation"):
            result[name] = rotation @ values
        else:
            result[name] = values.copy()
    return result


def prepare_sample(sample, midi_notes, fps, subject, piece, split, details_path=None):
    """Prepare a sample without writing files or imputing missing observations."""
    sample = Path(sample)
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError("fps must be positive and explicit")
    if split not in ("train", "valid", "test") or not subject or not piece:
        raise ValueError("subject, piece and train/valid/test split are required")
    raw_path = sample / "motion_hand_raw_flagged.csv"
    markers, raw = read_motion(raw_path)
    observed = np.isfinite(raw).all(axis=2)
    frame = keyboard_frame(markers, raw)
    times = np.arange(len(raw), dtype=float) / fps
    details_path = Path(details_path) if details_path is not None else None
    score, labels = read_events(sample / "fingering_events.csv", midi_notes,
                                details_path)
    if max(event["end"] for event in score["events"]) > times[-1] + 1 / fps:
        raise ValueError("MIDI extends beyond motion: check sample fps and time origin")
    if details_path is not None:
        details = json.loads(details_path.read_text(encoding="utf-8-sig"))
        source_duration = details["n_frames"] / details["fps"]
        if abs(len(raw) / fps - source_duration) > max(1 / fps, 1 / details["fps"]) + 1e-6:
            raise ValueError("motion duration disagrees with source metadata; check fps")
    keyboard = to_keyboard(raw, frame)
    arrays = {"time_sec": times, "marker_names": np.asarray(markers),
              "positions_keyboard_m": keyboard, "observed_mask": observed}
    features = hand_features(markers, keyboard)
    arrays.update(features)
    paths = [raw_path, sample / "fingering_events.csv", sample / "midi.mid"]
    if details_path is not None:
        paths.append(details_path)
    imputed_path = sample / "motion_hand_imputed.csv"
    imputed_fraction = 0.0
    if imputed_path.exists():
        imputed_markers, imputed = read_motion(imputed_path)
        if imputed_markers != markers or imputed.shape != raw.shape:
            raise ValueError("raw and imputed marker order/shape differ")
        finite = np.isfinite(imputed).all(axis=2)
        filled = ~observed & finite
        changed = observed & finite & (np.linalg.norm(imputed - raw, axis=2) > 1e-9)
        arrays.update(imputed_positions_keyboard_m=to_keyboard(imputed, frame),
                      imputed_available_mask=finite, inferred_filled_mask=filled,
                      changed_observed_mask=changed)
        imputed_fraction = float(filled.mean())
        paths.append(imputed_path)
    windows = note_windows(score["events"], labels, times, markers, observed)
    report = {"sample": sample.name, "subject": subject, "piece": piece, "split": split,
              "source_kind": "public_explorer_sample", "fps": fps, "frames": len(raw),
              "duration_sec": float(times[-1]), "markers": len(markers),
              "notes": len(score["events"]),
              "labeled_notes": sum(e["hand"] is not None for e in score["events"]),
              "missing_marker_fraction": float((~observed).mean()),
              "inferred_filled_fraction": imputed_fraction,
              "keyboard_frame": frame, "windows": len(windows),
              "isolated_in_hand_windows": sum(w["isolated_in_hand"] for w in windows),
              "fully_observed_windows": sum(w["observed_fraction"] == 1 for w in windows),
              "robot_expert_eligible": False,
              "fingering_details_used": str(details_path) if details_path else None,
              "validation": "MIDI alignment and motion structure only; no robot simulation",
              "sources": [{"file": path.name, "sha256": sha256(path)} for path in paths]}
    source_manifest = sample.parent / "sources.json"
    if source_manifest.exists():
        manifest = json.loads(source_manifest.read_text(encoding="utf-8-sig"))
        records = [item for item in manifest["files"] if item["sample"] == sample.name]
        for source in report["sources"]:
            matches = [item for item in records if item["file"] == source["file"]]
            if len(matches) != 1 or matches[0]["sha256"] != source["sha256"]:
                raise ValueError(f"download manifest hash mismatch: {source['file']}")
        report["download_provenance"] = {"revision": manifest["revision"], "files": records}
    return score, labels, arrays, windows, report


def verify_split_isolation(reports):
    """Reject reused participants, pieces or source bytes across data splits."""
    owners = {}
    for report in reports:
        if report["split"] not in ("train", "valid", "test"):
            raise ValueError("invalid split")
        identities = [("subject", report["subject"]), ("piece", report["piece"])]
        identities.extend(("sha256", item["sha256"]) for item in report["sources"])
        for identity in identities:
            previous = owners.setdefault(identity, report["split"])
            if previous != report["split"]:
                raise ValueError(f"split leakage for {identity[0]}: {identity[1]}")
    return True


def curriculum_fragments(events, max_notes=8):
    """Extract small, fully labeled overlap components without breaking chords.

    Unknown fingers must not enter the current RoboPianist fingering reward:
    upstream treats -1 as a Python index into right-hand fingers. Reject the
    entire connected component instead of dropping its unlabeled notes.
    """
    if max_notes < 1:
        raise ValueError("max_notes must be positive")
    groups = []
    for event in sorted(events, key=lambda e: (e["start"], e["end"], e["id"])):
        if not groups or event["start"] > max(e["end"] for e in groups[-1]) + 1e-9:
            groups.append([])
        groups[-1].append(event)
    fragments = []
    for index, group in enumerate(groups):
        if len(group) > max_notes or any(e["hand"] is None or e["finger"] is None for e in group):
            continue
        first = min(e["start"] for e in group)
        last = max(e["end"] for e in group)
        previous_end = max(e["end"] for e in groups[index - 1]) if index else 0.0
        next_start = min(e["start"] for e in groups[index + 1]) if index + 1 < len(groups) else last + .2
        origin = max(previous_end, first - .2)
        end = min(next_start, last + .2)
        relative = [{**event, "start": event["start"] - origin,
                     "end": event["end"] - origin} for event in group]
        fragments.append({"source_event_ids": [e["id"] for e in group],
                          "origin_sec": origin, "source_end_sec": end,
                          "events": relative, "robot_expert_eligible": False})
    return fragments


def note_sequence_bytes(events):
    """Encode the official note-seq NoteSequence subset used by RoboPianist.

    Field numbers are from magenta/note-seq/note_seq/protobuf/music.proto:
    NoteSequence.notes=8, total_time=9; Note pitch=1, velocity=2,
    start_time=3, end_time=4, part=10. Seconds are retained as doubles.
    All notes must be labeled: right 0..4, left 5..9, thumb to little.
    """
    validate_events({"format": "piano_fingering/1", "events": events})

    def varint(number):
        result = bytearray()
        while number >= 128:
            result.append((number & 127) | 128)
            number >>= 7
        result.append(number)
        return bytes(result)

    output = bytearray()
    for event in events:
        if event["hand"] is None or event["finger"] is None:
            raise ValueError("RoboPianist score export requires fully labeled notes")
        part = FINGERS.index(event["finger"]) + (5 if event["hand"] == "left" else 0)
        note = (b"\x08" + varint(event["note"]) + b"\x10" + varint(event["velocity"])
                + b"\x19" + struct.pack("<d", event["start"])
                + b"\x21" + struct.pack("<d", event["end"])
                + b"\x50" + varint(part))
        output.extend(b"\x42" + varint(len(note)) + note)
    output.extend(b"\x49" + struct.pack("<d", max(e["end"] for e in events)))
    return bytes(output)
