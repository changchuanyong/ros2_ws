"""Export observed MIDI events to a single-track Standard MIDI File."""

import json
import os
from pathlib import Path
import struct


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
