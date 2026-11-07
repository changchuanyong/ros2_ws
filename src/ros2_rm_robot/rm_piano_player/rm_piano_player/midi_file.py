"""Read MIDI scores and export observed events to Standard MIDI Files."""

from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path
import struct


@dataclass(frozen=True)
class ScoreNote:
    start: float
    end: float
    channel: int
    note: int
    velocity: int


def _read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("Truncated MIDI file")
    return data


def _read_delta(stream):
    value = 0
    for _ in range(4):
        byte = _read_exact(stream, 1)[0]
        value = (value << 7) | (byte & 127)
        if byte < 128:
            return value
    raise ValueError("Invalid MIDI variable length value")


def _track_events(data):
    stream = BytesIO(data)
    tick = 0
    running_status = None
    while stream.tell() < len(data):
        tick += _read_delta(stream)
        status = _read_exact(stream, 1)[0]
        if status < 128:
            if running_status is None:
                raise ValueError("MIDI running status is missing")
            stream.seek(-1, 1)
            status = running_status
        if status == 0xff:
            kind = _read_exact(stream, 1)[0]
            payload = _read_exact(stream, _read_delta(stream))
            running_status = None
            if kind == 0x51:
                if len(payload) != 3 or not any(payload):
                    raise ValueError("Invalid MIDI tempo")
                yield tick, "tempo", int.from_bytes(payload, "big")
            elif kind == 0x2f:
                return
        elif status in (0xf0, 0xf7):
            _read_exact(stream, _read_delta(stream))
            running_status = None
        elif status < 0xf0:
            running_status = status
            kind = status >> 4
            payload = _read_exact(stream, 1 if kind in (0xc, 0xd) else 2)
            if any(byte >= 128 for byte in payload):
                raise ValueError("Invalid MIDI channel data")
            if kind in (8, 9):
                yield tick, "note", (status & 15, payload[0], payload[1] if kind == 9 else 0)
        else:
            raise ValueError(f"Unsupported MIDI status 0x{status:02x}")
    raise ValueError("MIDI track has no end-of-track event")


def read_score(path):
    """Read complete notes with channel and tempo-adjusted times from PPQN MIDI."""
    with Path(path).open("rb") as stream:
        if _read_exact(stream, 4) != b"MThd":
            raise ValueError("Invalid MIDI header")
        header = _read_exact(stream, struct.unpack(">I", _read_exact(stream, 4))[0])
        if len(header) < 6:
            raise ValueError("Invalid MIDI header length")
        format_id, tracks, division = struct.unpack_from(">HHH", header)
        if format_id not in (0, 1) or not tracks or (format_id == 0 and tracks != 1):
            raise ValueError("Expected MIDI format 0 or 1")
        if not 0 < division < 0x8000:
            raise ValueError("Expected MIDI PPQN timing")
        events = []
        for _ in range(tracks):
            if _read_exact(stream, 4) != b"MTrk":
                raise ValueError("Invalid MIDI track header")
            size = struct.unpack(">I", _read_exact(stream, 4))[0]
            events.extend(_track_events(_read_exact(stream, size)))

    notes = []
    active = {}
    elapsed = last_tick = 0
    tempo = 500000
    for tick, kind, value in sorted(events, key=lambda event: event[0]):
        elapsed += (tick - last_tick) * tempo
        last_tick = tick
        seconds = elapsed / (division * 1_000_000)
        if kind == "tempo":
            tempo = value
            continue
        channel, note, velocity = value
        key = (channel, note)
        if velocity:
            if key in active:
                raise ValueError(f"Overlapping MIDI note {note} on channel {channel}")
            active[key] = seconds, velocity
        else:
            if key not in active:
                raise ValueError(f"MIDI note {note} released without a matching press")
            start, velocity = active.pop(key)
            if seconds <= start:
                raise ValueError(f"MIDI note {note} has no duration")
            notes.append(ScoreNote(start, seconds, channel, note, velocity))
    if active or not notes:
        raise ValueError("MIDI score must contain complete notes")
    return sorted(notes, key=lambda note: (note.start, note.channel, note.note))


def _variable_length(value):
    if not 0 <= value <= 0x0fffffff:
        raise ValueError('MIDI delta time out of range')
    result = [value & 0x7f]
    while value > 0x7f:
        value >>= 7
        result.insert(0, (value & 0x7f) | 0x80)
    return bytes(result)


def export_midi(events_path, output_path):
    """Stream actual input events; first event is time zero, one tick is 1 ms.

    Preserve note on/off, velocity, channel and sustain. Do not synthesize score
    notes or missing releases. Even zero events produce a valid empty MIDI file.
    JSONL retains original host timestamps for alignment with pressure samples.
    """
    output_path = Path(output_path)
    temporary = output_path.with_suffix(output_path.suffix + '.tmp')
    count = 0
    first_ns = None
    previous_tick = 0
    try:
        with temporary.open('xb') as output, Path(events_path).open(encoding='utf-8') as source:
            output.write(b'MThd' + struct.pack('>IHHH', 6, 0, 1, 500))
            output.write(b'MTrk\x00\x00\x00\x00')
            output.write(b'\x00\xff\x51\x03\x07\xa1\x20')  # 500000 us/quarter
            for line in source:
                event = json.loads(line)
                if event.get('event') != 'midi':
                    continue
                channel = event['channel']
                if not isinstance(channel, int) or not 0 <= channel <= 15:
                    raise ValueError('invalid MIDI channel')
                if event['type'] == 'sustain':
                    message = (0xb0 | channel, 64, event['value'])
                elif event['type'] in ('on', 'off'):
                    status = 0x90 if event['type'] == 'on' else 0x80
                    message = (status | channel, event['note'], event['velocity'])
                else:
                    raise ValueError('unknown MIDI event type')
                if any(not isinstance(v, int) or not 0 <= v <= 127 for v in message[1:]):
                    raise ValueError('invalid MIDI data byte')
                stamp = event['monotonic_ns']
                if not isinstance(stamp, int) or stamp < 0:
                    raise ValueError('invalid MIDI timestamp')
                if first_ns is None:
                    first_ns = stamp
                tick = (stamp - first_ns) // 1000000
                output.write(_variable_length(tick - previous_tick) + bytes(message))
                previous_tick = tick
                count += 1
            output.write(b'\x00\xff\x2f\x00')
            length = output.tell() - 22
            output.seek(18)
            output.write(struct.pack('>I', length))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return count
