"""Write raw hand feedback and playback events without blocking ROS callbacks."""

import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import queue
import threading
import time
import uuid

from rm_piano_player.midi_file import export_midi


class RecorderError(RuntimeError):
    """Recording cannot continue reliably; the caller must stop playback."""


CSV_FIELDS = (
    'schema_version', 'session_id', 'hand', 'uid', 'seq', 'field',
    'started_ns', 'finished_ns', 'wall_time_ns', 'received_ns',
    'register_address', 'valid', 'error',
) + tuple(f'value_{index:02d}' for index in range(30))
FEEDBACK_LENGTHS = {'position': 30, 'speed': 30, 'torque': 30, 'current': 30, 'force': 20}


def _snapshot(value):
    if not isinstance(value, dict):
        raise ValueError('record must be a dictionary')
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


class SessionRecorder:
    """Own one session directory and a bounded, single-writer background queue."""

    def __init__(self, base_dir, metadata, queue_size=2048):
        """Create output files before any movement can be authorized by the caller."""
        if isinstance(queue_size, bool) or not isinstance(queue_size, int) or queue_size <= 0:
            raise ValueError('queue_size must be a positive integer')
        self._metadata = _snapshot(metadata)
        self._queue = queue.Queue(maxsize=queue_size)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._error = ''
        self._closing = False
        self._outcome = 'interrupted'
        self._reason = ''
        self._files = {}
        self._stats = {'feedback_rows': 0, 'touch_frames': 0, 'event_rows': 0,
                       'telemetry_errors': 0, 'streams': {}, 'sequences': {},
                       'write_ack': {'count': 0, 'sum_latency_sec': 0.0,
                                     'max_latency_sec': 0.0}}
        self._created_ns = time.time_ns()
        name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ_') + uuid.uuid4().hex
        self.path = Path(base_dir).expanduser().resolve() / name
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.mkdir()
            self._write_metadata('recording', '')
            for name in ('feedback.csv', 'touch.jsonl', 'events.jsonl'):
                self._files[name] = (self.path / name).open('x', encoding='utf-8', newline='')
            self._csv = csv.DictWriter(self._files['feedback.csv'], fieldnames=CSV_FIELDS)
            self._csv.writeheader()
            self._flush_files()
        except Exception as error:
            for stream in self._files.values():
                stream.close()
            raise RecorderError(f'cannot create recording at {self.path}: {error}') from error
        self._thread = threading.Thread(target=self._run, name='piano-recording', daemon=True)
        self._thread.start()

    @property
    def error(self):
        """Return the latched failure, including asynchronous disk errors."""
        with self._lock:
            return self._error

    def _latch_error(self, message):
        with self._lock:
            if not self._error:
                self._error = str(message)
        self._stop.set()

    def _enqueue(self, kind, value):
        with self._lock:
            if self._error:
                raise RecorderError(self._error)
            if self._closing:
                raise RecorderError('recording is closing or closed')
            try:
                self._queue.put_nowait((kind, value))
            except queue.Full as error:
                self._latch_error('recording queue overflow; no further samples accepted')
                raise RecorderError(self._error) from error

    def record_event(self, event):
        """Queue a copy of a playback event; never wait for disk or queue space."""
        self._record('event', event)

    def record_telemetry(self, packet):
        """Queue raw telemetry, preserving per-transaction sampling timestamps."""
        self._record('telemetry', packet)

    def _record(self, kind, value):
        try:
            payload = _snapshot(value)
            payload.setdefault('received_ns', time.monotonic_ns())
            if kind == 'telemetry':
                packet_kind = payload.get('kind')
                if packet_kind not in ('feedback', 'touch', 'error', 'command_written'):
                    raise ValueError(f'unknown telemetry kind: {packet_kind}')
                if packet_kind in ('feedback', 'touch'):
                    values = payload.get('values')
                    if not isinstance(values, list) or any(
                            isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 65535
                            for v in values):
                        raise ValueError('telemetry values must be raw uint16 integers')
                    expected = FEEDBACK_LENGTHS.get(payload.get('field'))
                    if packet_kind == 'touch':
                        rows, cols = payload.get('rows'), payload.get('cols')
                        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0
                               for v in (rows, cols)):
                            raise ValueError('touch rows and cols must be positive integers')
                        expected = rows * cols
                    if expected is None or len(values) != expected:
                        raise ValueError('telemetry values do not match field or matrix size')
            self._enqueue(kind, payload)
        except (ValueError, TypeError, OverflowError) as error:
            self._latch_error(f'invalid recording payload: {error}')
            raise RecorderError(self.error) from error

    def _write_record(self, kind, payload):
        """Write one accepted record on the background thread only."""
        packet_kind = payload.get('kind') if kind == 'telemetry' else None
        if packet_kind == 'feedback':
            row = {key: payload.get(key, '') for key in CSV_FIELDS[:13]}
            row.update({f'value_{i:02d}': v for i, v in enumerate(payload['values'])})
            self._csv.writerow(row)
            self._files['feedback.csv'].flush()
            self._stats['feedback_rows'] += 1
        else:
            filename = 'touch.jsonl' if packet_kind == 'touch' else 'events.jsonl'
            stream = self._files[filename]
            stream.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
            self._stats['touch_frames' if packet_kind == 'touch' else 'event_rows'] += 1
        if kind == 'telemetry':
            self._track_telemetry(payload)
        if payload.get('event') == 'write_ack':
            latency = payload.get('ack_latency_sec')
            if isinstance(latency, (int, float)) and not isinstance(latency, bool):
                if math.isfinite(latency) and latency >= 0:
                    stats = self._stats['write_ack']
                    stats['count'] += 1
                    stats['sum_latency_sec'] += latency
                    stats['max_latency_sec'] = max(stats['max_latency_sec'], latency)

    def _track_telemetry(self, packet):
        identity = '/'.join(str(packet.get(key, '')) for key in ('session_id', 'hand', 'uid'))
        seq = packet.get('seq')
        if isinstance(seq, int) and not isinstance(seq, bool):
            sequences = self._stats['sequences']
            if identity not in sequences:
                sequences[identity] = {'first': seq, 'last': seq, 'missing': 0,
                                       'out_of_order_or_duplicate': 0}
            else:
                entry = sequences[identity]
                if seq > entry['last']:
                    entry['missing'] += seq - entry['last'] - 1
                    entry['last'] = seq
                else:
                    entry['out_of_order_or_duplicate'] += 1
        if packet.get('kind') == 'error' or packet.get('valid') is False:
            self._stats['telemetry_errors'] += 1
            return
        if packet.get('kind') not in ('feedback', 'touch'):
            return
        stamp = packet.get('finished_ns')
        if not isinstance(stamp, int) or isinstance(stamp, bool):
            return
        key = identity + '/' + str(packet.get('field'))
        if packet['kind'] == 'touch':
            key += '/' + str(packet.get('sensor'))
        streams = self._stats['streams']
        if key not in streams:
            streams[key] = {'samples': 1, 'first_ns': stamp, 'last_ns': stamp,
                            'max_gap_ns': 0}
        else:
            entry = streams[key]
            entry['samples'] += 1
            entry['max_gap_ns'] = max(entry['max_gap_ns'], stamp - entry['last_ns'])
            entry['first_ns'] = min(entry['first_ns'], stamp)
            entry['last_ns'] = max(entry['last_ns'], stamp)

    def _flush_files(self):
        for stream in self._files.values():
            stream.flush()

    def _write_metadata(self, outcome, reason):
        metadata = _snapshot(self._metadata)
        stats = _snapshot(self._stats)
        for stream in stats['streams'].values():
            duration = stream['last_ns'] - stream['first_ns']
            stream['observed_hz'] = ((stream['samples'] - 1) * 1e9 / duration
                                     if duration > 0 else None)
        ack = stats['write_ack']
        ack['mean_latency_sec'] = (ack['sum_latency_sec'] / ack['count']
                                   if ack['count'] else None)
        metadata['recording'] = {
            'format_version': 1, 'outcome': outcome, 'reason': reason,
            'incomplete': outcome != 'completed', 'failed': outcome == 'failed',
            'created_wall_time_ns': self._created_ns,
            'ended_wall_time_ns': time.time_ns() if outcome != 'recording' else None,
            'feedback_units': 'raw unsigned 16-bit registers; no N, Nm or A conversion',
            'sampling': 'sequential transactions; each row/frame has its own time interval',
            'monotonic_clock': 'local host monotonic_ns',
            'sequence_note': 'missing counts gaps after first observed telemetry packet only',
            'statistics': stats,
        }
        temporary = self.path / 'metadata.json.tmp'
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump(metadata, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path / 'metadata.json')
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _run(self):
        try:
            while not self._stop.is_set() or not self._queue.empty():
                try:
                    kind, payload = self._queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    if kind == 'flush':
                        self._flush_files()
                    else:
                        self._write_record(kind, payload)
                finally:
                    if kind == 'flush':
                        payload.set()
                    self._queue.task_done()
        except Exception as error:
            self._latch_error(f'recording write failed: {error}')
        finally:
            for stream in self._files.values():
                try:
                    stream.flush()
                    os.fsync(stream.fileno())
                except Exception as error:
                    self._latch_error(f'recording flush failed: {error}')
                finally:
                    try:
                        stream.close()
                    except Exception as error:
                        self._latch_error(f'recording close failed: {error}')
            if self._metadata.get('midi_input'):
                try:
                    self._stats['midi_events'] = export_midi(
                        self.path / 'events.jsonl', self.path / 'performance.mid')
                except Exception as error:
                    self._latch_error(f'cannot export recorded MIDI: {error}')
            outcome = 'failed' if self.error else self._outcome
            reason = self.error or self._reason
            try:
                self._write_metadata(outcome, reason)
            except Exception as error:
                self._latch_error(f'cannot finalize recording metadata: {error}')

    def flush(self, timeout=5.0):
        """Wait for previously accepted records; use outside timing callbacks."""
        barrier = threading.Event()
        self._enqueue('flush', barrier)
        if not barrier.wait(timeout):
            self._latch_error('recording flush timed out')
        if self.error:
            raise RecorderError(self.error)

    def close(self, outcome, reason='', timeout=5.0):
        """Drain accepted records, close files and finalize metadata before returning."""
        with self._lock:
            if not self._closing:
                self._closing = True
                self._outcome, self._reason = str(outcome), str(reason)
                self._stop.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            self._latch_error('recording close timed out; finalization incomplete')
        if self.error:
            raise RecorderError(self.error)
        return self.path
