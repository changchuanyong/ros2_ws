"""Capture MIDI input arrival times without ROS, disk I/O, or output messages."""

from collections import deque
import threading
import time


class MidiCaptureError(RuntimeError):
    """MIDI input cannot be opened or captured reliably."""


def _backend(backend):
    if backend is not None:
        return backend
    from rm_piano_player import raw_midi
    return raw_midi


def list_inputs(backend=None):
    """List exact input names; never open an output or silently choose a device."""
    try:
        names = list(_backend(backend).get_input_names())
        if any(not isinstance(name, str) or not name for name in names):
            raise ValueError('backend returned invalid MIDI input names')
        return names
    except MidiCaptureError:
        raise
    except Exception as error:
        raise MidiCaptureError(
            'Cannot enumerate raw MIDI inputs; check /dev/snd/midiC*D* '
            f'and the connected USB MIDI device: {error}') from error


def _integer(value, maximum, name):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f'invalid MIDI {name}')
    return value


class MidiCapture:
    """Queue callback arrivals; these are host times, not sensor scan timestamps.

    A backend can keep a disconnected port open. Missing note deadlines must
    therefore also be checked by the benchmark; silence alone is not health.
    """

    def __init__(self, input_name, *, queue_size=2048, backend=None):
        """Open exactly one named input after validating the bounded queue."""
        if not isinstance(input_name, str) or not input_name.strip():
            raise ValueError('midi_input must be a nonempty exact input name')
        if type(queue_size) is not int or queue_size <= 0:
            raise ValueError('MIDI queue_size must be a positive integer')
        self._lock = threading.Lock()
        self._queue = deque()
        self._queue_size = queue_size
        self._closed = False
        self._error = ''
        self._port = None
        self.input_name = input_name
        backend = _backend(backend)
        names = list_inputs(backend)
        if names.count(input_name) != 1:
            raise MidiCaptureError(
                f'MIDI input must match exactly one available port: {input_name!r}; '
                f'available inputs: {names!r}')
        try:
            self._port = backend.open_input(input_name, callback=self._receive)
            if self._port is None:
                raise MidiCaptureError('backend did not return a MIDI input port')
            if self.error:
                raise MidiCaptureError(self.error)
        except Exception as error:
            self.close()
            raise MidiCaptureError(f'Cannot open MIDI input {input_name!r}: {error}') from error

    def _latch_error(self, reason):
        with self._lock:
            if not self._error:
                self._error = str(reason)

    @property
    def error(self):
        """Return a latched queue/backend error, including an unexpectedly closed port."""
        with self._lock:
            port = None if self._closed else self._port
        if port is not None:
            try:
                if getattr(port, 'error', ''):
                    self._latch_error(port.error)
                if port.closed:
                    self._latch_error('MIDI input port closed unexpectedly')
            except Exception as error:
                self._latch_error(f'MIDI input status failed: {error}')
        with self._lock:
            return self._error

    def _receive(self, message):
        """Timestamp at callback entry and enqueue; never call the backend here."""
        monotonic_ns, wall_time_ns = time.monotonic_ns(), time.time_ns()
        with self._lock:
            if self._closed or self._error:
                return
            try:
                kind = message.type
                if kind in ('note_on', 'note_off'):
                    velocity = _integer(message.velocity, 127, 'velocity')
                    event = {
                        'type': 'on' if kind == 'note_on' and velocity else 'off',
                        'note': _integer(message.note, 127, 'note'), 'velocity': velocity,
                    }
                elif kind == 'control_change' and message.control == 64:
                    event = {'type': 'sustain', 'value': _integer(message.value, 127, 'value')}
                else:
                    return
                event.update(channel=_integer(message.channel, 15, 'channel'),
                             monotonic_ns=monotonic_ns, wall_time_ns=wall_time_ns)
                if len(self._queue) >= self._queue_size:
                    self._error = 'MIDI capture queue overflow; later events were rejected'
                    return
                self._queue.append(event)
            except Exception as error:
                self._error = f'MIDI callback failed: {error}'

    def drain(self):
        """Return accepted events even after a fault, so the caller can preserve evidence."""
        self.error
        with self._lock:
            events = list(self._queue)
            self._queue.clear()
            return events

    def close(self):
        """Stop callbacks and close once, without discarding queued evidence."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except Exception as error:
                self._latch_error(f'MIDI input close failed: {error}')
