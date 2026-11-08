"""Adapt MIDI and existing fingering files to the planner's event contract."""

from pathlib import Path

from rm_mujoco.performance import load_events, validate_events, validate_physical_key_spans

from .midi_file import read_score


def load_score(path, hand="right", left_max_note=59):
    """Use explicit MIDI hand selection or a pitch split; preserve YAML labels."""
    path = Path(path)
    if hand not in ("left", "right", "both"):
        raise ValueError("hand must be left, right or both")
    if isinstance(left_max_note, bool) or not isinstance(left_max_note, int) \
            or not 21 <= left_max_note <= 108:
        raise ValueError("left_max_note must be an integer in 21..108")
    if path.suffix.lower() in (".mid", ".midi"):
        events = []
        for index, note in enumerate(read_score(path), 1):
            side = hand
            if hand == "both":
                side = "left" if note.note <= left_max_note else "right"
            events.append({"id": index, "note": note.note, "start": note.start,
                           "end": note.end, "velocity": note.velocity,
                           "hand": side, "finger": None})
        document = {"format": "piano_fingering/1", "source": str(path.resolve()),
                    "events": events}
    else:
        document = load_events(path)
    validate_events(document, path)
    for event in document["events"]:
        side = event.get("hand")
        if side is None:
            side = "left" if event["note"] <= left_max_note else "right"
        if hand != "both" and side != hand:
            raise ValueError(f"event {event['id']} belongs to {side}; select --hand both "
                             "or provide a score for the selected hand")
    validate_physical_key_spans(
        ((e["start"], e["end"], e["note"]) for e in document["events"]), path)
    return document
