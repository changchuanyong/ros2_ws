"""Read Linux ALSA raw MIDI character devices without Sequencer or MIDI output."""

import os
from pathlib import Path
import re
import select
import stat
import threading
from types import SimpleNamespace


_DEVICE = re.compile(r'/dev/snd/midiC[0-9]+D[0-9]+\Z')


def _is_sound_device(info):
    return stat.S_ISCHR(info.st_mode) and os.major(info.st_rdev) == 116


def get_input_names():
    """Return explicit device paths, without opening or choosing a MIDI device."""
    names = []
    for path in sorted(Path('/dev/snd').glob('midiC*D*')):
        try:
            if _DEVICE.fullmatch(str(path)) and _is_sound_device(path.lstat()):
                names.append(str(path))
        except FileNotFoundError:
            continue
    return names


class MidiStreamParser:
    """Parse channel messages across reads with bounded storage and running status.

    Real-time bytes may occur inside any message. System common/SysEx status
    cancels running status; ignored SysEx data is never buffered.
    """

    def __init__(self, callback):
        self.callback = callback
        self.status = None
        self.data = []

    def feed(self, chunk):
        """Deliver note and controller messages; discard unrelated MIDI traffic."""
        for byte in chunk:
            if byte >= 0xF8:
                continue
            if byte & 0x80:
                self.data.clear()
                self.status = byte if byte < 0xF0 else None
                continue
            if self.status is None:
                continue
            kind = self.status >> 4
            self.data.append(byte)
            length = 1 if kind in (0xC, 0xD) else 2
            if len(self.data) != length:
                continue
            data, self.data = self.data, []
            channel = self.status & 0xF
            if kind in (0x8, 0x9):
                self.callback(SimpleNamespace(
                    type='note_on' if kind == 0x9 else 'note_off', channel=channel,
                    note=data[0], velocity=data[1]))
            elif kind == 0xB:
                self.callback(SimpleNamespace(
                    type='control_change', channel=channel, control=data[0], value=data[1]))


class RawMidiInput:
    """Own a read-only nonblocking descriptor and a bounded-latency reader thread."""

    def __init__(self, name, callback):
        if not isinstance(name, str) or not _DEVICE.fullmatch(name):
            raise ValueError('MIDI input must be an exact /dev/snd/midiC*D* device path')
        self.closed = False
        self.error = ''
        self._stop = threading.Event()
        self._parser = MidiStreamParser(callback)
        self._fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            if not _is_sound_device(os.fstat(self._fd)):
                raise ValueError('MIDI input must be an ALSA character device')
            self._poll = select.poll()
            self._poll.register(self._fd, select.POLLIN | select.POLLERR | select.POLLHUP)
            self._thread = threading.Thread(target=self._read, name='raw-midi-input', daemon=True)
            self._thread.start()
        except Exception:
            os.close(self._fd)
            self.closed = True
            raise

    def _read(self):
        try:
            while not self._stop.is_set():
                for _, events in self._poll.poll(50):
                    if self._stop.is_set():
                        return
                    if events & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                        raise OSError('raw MIDI device disconnected or reported an input error')
                    if events & select.POLLIN:
                        try:
                            chunk = os.read(self._fd, 256)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            raise OSError('raw MIDI device reached end of input')
                        self._parser.feed(chunk)
        except Exception as error:
            if not self._stop.is_set():
                self.error = f'Raw MIDI input failed: {error}'
        finally:
            self.closed = True

    def close(self):
        """Stop the reader before releasing its descriptor; safe to call twice."""
        self._stop.set()
        self._thread.join(timeout=1)
        if self._thread.is_alive():
            raise RuntimeError('raw MIDI reader did not stop')
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self.closed = True


def open_input(name, callback):
    """Open an input only; this module intentionally provides no output API."""
    return RawMidiInput(name, callback)
