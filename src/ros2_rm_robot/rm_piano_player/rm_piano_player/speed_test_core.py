"""Fixed score timing and strict MIDI scoring for stationary right-hand trials."""

import math
from numbers import Real
import statistics


DEFAULT_RATES = (2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 16.0)
PATTERNS = {'repeat': ('E',), 'alternate': ('C', 'D'), 'scale': ('C', 'D', 'E', 'F', 'G')}
MIDI_NOTES = {'C': 60, 'D': 62, 'E': 64, 'F': 65, 'G': 67}
TIMING_FRACTION = 0.2


class BenchmarkFailure(RuntimeError):
    """A trial failed; no subsequent notes or faster trial may be admitted."""


def _finite(value, name, *, minimum=0.0, maximum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{name} must be a finite number')
    try:
        value = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError(f'{name} must be a finite number') from error
    if (not math.isfinite(value) or value < minimum or (positive and value == minimum) or
            (maximum is not None and value > maximum)):
        raise ValueError(f'{name} is outside its permitted range')
    return value


def parse_rates(text):
    """Parse increasing trial targets, capped at the chosen 16-note/s challenge."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('rates must be a nonempty comma-separated string')
    try:
        values = tuple(_finite(float(part), 'rate', positive=True, maximum=16.0)
                       for part in text.split(','))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('rates must be finite, positive and no greater than 16') from error
    if any(after <= before for before, after in zip(values, values[1:])):
        raise ValueError('rates must be strictly increasing without duplicates')
    return values


def make_score(pattern, rate, count=20, start=0.0):
    """Plan alternating press/release edges once, without execution-time sliding."""
    if pattern not in PATTERNS:
        raise ValueError('pattern must be repeat, alternate or scale')
    rate = _finite(rate, 'rate', positive=True, maximum=16.0)
    start = _finite(start, 'start')
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError('count must be an integer within 1..1000')
    period = 1.0 / rate
    score = []
    for index in range(count):
        symbol = PATTERNS[pattern][index % len(PATTERNS[pattern])]
        edges = (('on', 0.0, 'PRESS_' + symbol), ('off', 0.5, 'READY'))
        for event_type, offset, pose in edges:
            planned_at = start + (index + offset) * period
            score.append({
                'event_index': len(score), 'note_index': index + 1,
                'type': event_type, 'note': MIDI_NOTES[symbol], 'pose': pose,
                'planned_at': planned_at, 'period': period,
                'deadline': planned_at + TIMING_FRACTION * period,
            })
    return score


def _distribution(values):
    if not values:
        return {'count': 0, 'mean': None, 'stddev': None, 'max_abs': None, 'p95_abs': None}
    ordered = sorted(abs(value) for value in values)
    position = 0.95 * (len(ordered) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    percentile = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return {'count': len(values), 'mean': statistics.fmean(values),
            'stddev': statistics.pstdev(values), 'max_abs': ordered[-1], 'p95_abs': percentile}


class MidiJudge:
    """Match exact ordered MIDI edges to disjoint score windows and sent commands.

    Times are host monotonic seconds. MIDI callback receipt is an observation
    timestamp, not a calibrated mechanical-contact or acoustic-onset timestamp.
    A late repeated note cannot be reassigned to the next score event.
    """

    def __init__(self, score, timing_fraction=TIMING_FRACTION):
        self.timing_fraction = _finite(timing_fraction, 'timing_fraction',
                                       positive=True, maximum=TIMING_FRACTION)
        if not isinstance(score, (list, tuple)) or not score or len(score) % 2:
            raise ValueError('score must contain complete on/off pairs')
        self._score = [dict(event) for event in score]
        self.period = _finite(self._score[0].get('period'), 'period', positive=True)
        first = _finite(self._score[0].get('planned_at'), 'planned_at')
        for index, event in enumerate(self._score):
            if (event.get('event_index') != index or event.get('note_index') != index // 2 + 1 or
                    event.get('type') != ('off' if index % 2 else 'on') or
                    type(event.get('note')) is not int or
                    event['note'] not in MIDI_NOTES.values()):
                raise ValueError('score events must be ordered C4..G4 on/off pairs')
            planned_at = _finite(event.get('planned_at'), 'planned_at')
            if (not math.isclose(planned_at, first + index * self.period / 2,
                                 rel_tol=0.0, abs_tol=1e-8) or
                    event.get('period') != self.period or
                    (index % 2 and event['note'] != self._score[index - 1]['note'])):
                raise ValueError('score must retain uniformly spaced paired timing')
        self.window = self.period * self.timing_fraction
        self._sent = {}
        self._acks = {}
        self._matches = []
        self._received = {'on': 0, 'off': 0}
        self._failure = ''
        self._failure_type = ''
        self._active = set()
        self._last_midi_time = None

    @property
    def done(self):
        """Return whether all MIDI edges matched; command ACKs are checked at finish."""
        return not self.failed and len(self._matches) == len(self._score)

    @property
    def failed(self):
        return bool(self._failure)

    @property
    def reason(self):
        return self._failure

    def _fail(self, failure_type, reason):
        if not self._failure:
            self._failure_type, self._failure = failure_type, reason
        raise BenchmarkFailure(self._failure)

    def _healthy(self):
        if self.failed:
            raise BenchmarkFailure(self._failure)

    def note_command_sent(self, event_index, sent_at):
        """Admit each scheduled edge once; never accept an overdue catch-up send."""
        self._healthy()
        sent_at = _finite(sent_at, 'sent_at')
        if type(event_index) is not int or event_index != len(self._sent) or (
                not 0 <= event_index < len(self._score)):
            self._fail('command_order', 'duplicate, skipped or invalid command index')
        if event_index and event_index - 1 not in self._acks:
            self._fail('command_pending', 'previous command has no write acknowledgement')
        planned = self._score[event_index]['planned_at']
        if sent_at < planned - 1e-9 or sent_at > planned + self.window + 1e-9:
            self._fail('command_timing', f'command {event_index} missed its fixed score window')
        self.check_timeout(sent_at)
        self._sent[event_index] = sent_at

    def record_command_ack(self, event_index, received_at):
        """Keep transport timing separately; MIDI may arrive before the ROS ACK."""
        self._healthy()
        received_at = _finite(received_at, 'received_at')
        if (type(event_index) is not int or event_index not in self._sent or
                event_index in self._acks or received_at < self._sent[event_index]):
            self._fail('command_ack', 'invalid, duplicate or unsent command acknowledgement')
        self._acks[event_index] = received_at

    def accept_midi(self, event_type, note, received_at, velocity=0):
        """Match one normalized on/off message, retaining the original planned time."""
        self._healthy()
        received_at = _finite(received_at, 'received_at')
        if (event_type not in ('on', 'off') or type(note) is not int or not 0 <= note <= 127 or
                type(velocity) is not int or not 0 <= velocity <= 127):
            self._fail('invalid_midi', 'invalid normalized MIDI note event')
        self._received[event_type] += 1
        if self._last_midi_time is not None and received_at < self._last_midi_time:
            self._fail('midi_order', 'MIDI receipt timestamps moved backwards')
        self._last_midi_time = received_at
        self.check_timeout(received_at)
        index = len(self._matches)
        if index >= len(self._score):
            self._fail('extra_midi', 'extra MIDI event after the final release')
        event = self._score[index]
        if event_type != event['type'] or note != event['note']:
            self._fail('wrong_midi', f'expected {event["type"]} {event["note"]}, '
                       f'got {event_type} {note} at event {index}')
        if index not in self._sent or received_at < self._sent[index]:
            self._fail('unsent_midi', f'MIDI event {index} precedes its position command')
        error = received_at - event['planned_at']
        if abs(error) > self.window + 1e-9:
            self._fail('midi_timing', f'MIDI event {index} missed its fixed score window')
        if event_type == 'on':
            if self._active:
                self._fail('held_key', 'new note began before the previous note released')
            self._active.add(note)
        else:
            if note not in self._active:
                self._fail('extra_release', 'note-off without a matching note-on')
            self._active.remove(note)
        match = {**event, 'received_at': received_at, 'error_sec': error, 'velocity': velocity}
        self._matches.append(match)
        return dict(match)

    def check_timeout(self, now):
        """Latch the first expired edge; callers must drain captured MIDI first."""
        self._healthy()
        now = _finite(now, 'now')
        index = len(self._matches)
        if index < len(self._score):
            event = self._score[index]
            if now > event['planned_at'] + self.window + 1e-9:
                self._fail('missing_midi', f'missing {event["type"]} {event["note"]} '
                           f'at event {index}; no later note can replace it')

    def finish(self):
        """Require all notes, releases and serial confirmations before passing."""
        self._healthy()
        if not self.done or self._active or len(self._acks) != len(self._score):
            self._fail('incomplete_trial', 'trial ended without every MIDI edge and command ACK')
        return self.report()

    def report(self):
        """Describe measured timing and failures without changing trial state."""
        onsets = [event['received_at'] for event in self._matches if event['type'] == 'on']
        intervals = [after - before for before, after in zip(onsets, onsets[1:])]
        errors = [event['error_sec'] for event in self._matches]
        ack_latency = [stamp - self._sent[index] for index, stamp in self._acks.items()]
        return {
            'passed': self.done and len(self._acks) == len(self._score),
            'failure_type': self._failure_type, 'reason': self.reason,
            'target_rate_hz': 1.0 / self.period, 'timing_window_sec': self.window,
            'expected_notes': len(self._score) // 2, 'matched_notes': len(onsets),
            'matched_releases': len(self._matches) - len(onsets),
            'received_note_on': self._received['on'], 'received_note_off': self._received['off'],
            'sent_commands': len(self._sent), 'acknowledged_commands': len(self._acks),
            'held_notes': sorted(self._active),
            'actual_note_rate_hz': ((len(onsets) - 1) / (onsets[-1] - onsets[0])
                                    if len(onsets) > 1 else None),
            'timing_error_sec': _distribution(errors),
            'inter_onset_error_sec': _distribution([value - self.period for value in intervals]),
            'command_ack_latency_sec': _distribution(ack_latency),
        }
