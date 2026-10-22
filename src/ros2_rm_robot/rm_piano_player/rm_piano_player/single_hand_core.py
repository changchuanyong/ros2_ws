"""Validate calibrated command poses and schedule one fixed right-hand melody."""

import math
from numbers import Real

import yaml


POSE_NAMES = ('READY', 'PRESS_C', 'PRESS_D', 'PRESS_E', 'PRESS_F', 'PRESS_G')
MELODY = ('E', 'E', 'F', 'G', 'G', 'F', 'E', 'D', 'C', 'C', 'D', 'E', 'E', 'D', 'D')
MIDI_NOTES = {'C': 60, 'D': 62, 'E': 64, 'F': 65, 'G': 67}


def load_pose_config(path):
    """Read a pose document without supplying executable fallback positions."""
    with open(path, encoding='utf-8') as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict) or not isinstance(config.get('poses'), dict):
        raise ValueError('pose configuration must contain a poses mapping')
    return config


def _positions(values):
    if not isinstance(values, (list, tuple)) or len(values) != 20:
        raise ValueError('positions must contain exactly 20 numeric command values')
    result = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError('positions must be numbers, not booleans or strings')
        try:
            number = float(value)
        except (ValueError, OverflowError) as error:
            raise ValueError('positions must be finite and within 0..255') from error
        if not math.isfinite(number) or not 0 <= number <= 255:
            raise ValueError('positions must be finite and within 0..255')
        result.append(number)
    return result


def calibration_report(config):
    """Report all six poses, including incomplete templates, without raising."""
    poses = config.get('poses', {}) if isinstance(config, dict) else {}
    if not isinstance(poses, dict):
        poses = {}
    report = {}
    for name in POSE_NAMES:
        errors = []
        entry = poses.get(name)
        verified = False
        if not isinstance(entry, dict):
            errors.append('missing pose mapping')
        else:
            try:
                _positions(entry.get('positions'))
            except ValueError as error:
                errors.append(str(error))
            if not isinstance(entry.get('verified'), bool):
                errors.append('verified must be true or false')
            verified = entry.get('verified') is True
        report[name] = {'valid': not errors, 'verified': verified, 'errors': errors}
    return report


def validate_execution(config, mode='pose_test', pose='READY'):
    """Require complete selected poses, plus human verification for a melody."""
    _selection(mode, pose)
    required = POSE_NAMES if mode == 'melody' else tuple(dict.fromkeys(('READY', pose)))
    report = calibration_report(config)
    errors = []
    for name in required:
        entry = report[name]
        if not entry['valid']:
            errors.append(f'{name}: ' + '; '.join(entry['errors']))
        if mode == 'melody' and not entry['verified']:
            errors.append(f'{name}: not verified by calibration')
    if errors:
        raise ValueError('; '.join(errors))
    return {name: _positions(config['poses'][name]['positions']) for name in required}


def _selection(mode, pose):
    if mode not in ('pose_test', 'melody'):
        raise ValueError('mode must be pose_test or melody')
    if pose not in POSE_NAMES:
        raise ValueError('pose must be READY or PRESS_C through PRESS_G')


def _positive_duration(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{name} must be a finite positive number')
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError(f'{name} must be a finite positive number') from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f'{name} must be a finite positive number')
    return number


class Playback:
    """Advance at most one position command per tick using actual send times.

    The caller must check communication health before every method that can
    return a command. Timing describes command progress, never key contact or
    audible feedback. The caller publishes returned commands immediately.
    """

    def __init__(self, poses, mode='pose_test', pose='READY',
                 press_duration=0.5, release_duration=0.5, ready_settle=1.0):
        """Create a stopped clock; start() is called only after driver readiness."""
        _selection(mode, pose)
        required = POSE_NAMES if mode == 'melody' else tuple(dict.fromkeys(('READY', pose)))
        self.poses = {name: _positions(poses.get(name)) for name in required}
        self.press_duration = _positive_duration(press_duration, 'press_duration')
        self.release_duration = _positive_duration(release_duration, 'release_duration')
        self.ready_settle = _positive_duration(ready_settle, 'ready_settle')
        self.notes = MELODY if mode == 'melody' else (() if pose == 'READY' else (pose[-1],))
        self._deadline = None
        self._last_time = None
        self.status = {
            'phase': 'idle', 'note_index': 0, 'target_pose': None,
            'sent_at': None, 'reason': '', 'done': False,
        }

    @property
    def done(self):
        """Return whether normal completion, stop, or failure is latched."""
        return self.status['done']

    def _time(self, now):
        if isinstance(now, bool) or not isinstance(now, Real) or not math.isfinite(now):
            raise ValueError('now must be a finite monotonic time')
        if self._last_time is not None and now < self._last_time:
            raise ValueError('monotonic time must not go backwards')
        self._last_time = now

    def _command(self, name, index, now, phase, duration):
        note = MIDI_NOTES[self.notes[index - 1]] if index else None
        self.status.update(
            phase=phase, note_index=index, target_pose=name, sent_at=now)
        self._deadline = now + duration
        return [{'pose': name, 'note_index': index, 'note': note, 'sent_at': now}]

    def start(self, now):
        """Send exactly one initial READY once communication is healthy."""
        if self.done or self.status['phase'] != 'idle':
            return []
        self._time(now)
        return self._command('READY', 0, now, 'settling', self.ready_settle)

    def tick(self, now):
        """Send a due command without catching up or shortening the next phase."""
        if self.done or self.status['phase'] == 'idle':
            return []
        self._time(now)
        if now < self._deadline:
            return []
        index = self.status['note_index']
        if self.status['phase'] == 'pressing':
            return self._command('READY', index, now, 'releasing', self.release_duration)
        if index == len(self.notes):
            self.status.update(phase='completed', done=True)
            return []
        index += 1
        return self._command(
            'PRESS_' + self.notes[index - 1], index, now, 'pressing', self.press_duration)

    def stop(self, now, healthy=True):
        """Latch a stop, optionally releasing once if a press was sent safely."""
        if self.done:
            return []
        self._time(now)
        commands = []
        if healthy and self.status['phase'] == 'pressing':
            commands = self._command(
                'READY', self.status['note_index'], now, 'releasing', self.release_duration)
        self.status.update(phase='stopped', reason='stop requested', done=True)
        return commands

    def fail(self, reason):
        """Latch a fault without generating a release or any later command."""
        if not self.done:
            self.status.update(phase='failed', reason=str(reason), done=True)
        return []
