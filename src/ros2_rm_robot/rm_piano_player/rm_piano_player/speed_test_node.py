"""Measure the stationary right-hand command-to-MIDI chain on a fixed score."""

import json
import math
import os
import time

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from std_msgs.msg import String

from rm_piano_player.midi_capture import MidiCapture
from rm_piano_player.single_hand_core import calibration_report, load_pose_config
from rm_piano_player.single_hand_node import SingleHandPiano
from rm_piano_player.speed_test_core import (
    BenchmarkFailure, MidiJudge, PATTERNS, TIMING_FRACTION, make_score, parse_rates,
)


class SpeedTestNode(SingleHandPiano):
    """Reuse session identity, telemetry recording and transport fault gates."""

    def __init__(self, midi_factory=MidiCapture, **kwargs):
        self._speed_initialized = False
        self._capture = None
        self._benchmark_config = {}
        self._trial_results = []
        self._judge = None
        self._score = []
        self._next_event = 0
        self._pending_event = None
        self._rate_index = 0
        self._round_index = 0
        self._trial_due = None
        self._trial_closed = True
        self._trial_saved = False
        self._ending = False
        self._end_phase = ''
        self._end_reason = ''
        self._release_sent = False
        self._run_dir = None
        self._destroyed = False
        super().__init__(manage_midi=False, **kwargs)
        try:
            defaults = {
                'pattern': 'repeat', 'rates': '2,4,6,8,10,12,16',
                'notes_per_trial': 20, 'repeats': 3, 'trial_rest': 1.0,
                'calibration_confirmed': False,
            }
            for name, value in defaults.items():
                self.declare_parameter(name, value)
            values = {name: self.get_parameter(name).value for name in defaults}
            values['midi_input'] = self.get_parameter('midi_input').value
            self._rates = parse_rates(values['rates'])
            make_score(values['pattern'], self._rates[0], values['notes_per_trial'])
            if type(values['repeats']) is not int or not 1 <= values['repeats'] <= 10:
                raise ValueError('repeats must be an integer within 1..10')
            if not math.isfinite(values['trial_rest']) or values['trial_rest'] <= 0:
                raise ValueError('trial_rest must be finite and positive')
            self._benchmark_config = {
                **values, 'rates': list(self._rates),
                'ready_settle': self.get_parameter('ready_settle').value,
                'timing_fraction': TIMING_FRACTION,
                'schedule': 'fixed score; each press/release uses half a period',
                'command_gate': 'previous write ACK required; fixed score is never shifted',
                'intervals': 'actual intervals include allowed timing jitter; see recorded errors',
                'legacy_hold_parameters_used': False,
                'scope': 'full 20-value PRESS/READY poses; no chords or overlapping fingers',
                'standard_protocol': values['notes_per_trial'] == 20 and values['repeats'] == 3,
            }
            self._speed_initialized = True
            if not self.get_parameter('execute').value:
                config = load_pose_config(self.get_parameter('pose_config').value)
                self._publish_status({
                    'phase': 'dry_run', 'done': True, 'execute': False,
                    'reason': '', 'calibration': calibration_report(config),
                    'pattern_notes': list(PATTERNS[values['pattern']]),
                    'schedule': [make_score(values['pattern'], rate, values['notes_per_trial'])
                                 for rate in self._rates],
                })
                return
            if not values['calibration_confirmed']:
                raise ValueError('speed execution requires calibration_confirmed=true '
                                 'after physical C4..G4 press/release verification')
            if self.get_parameter('mode').value != 'melody' or self._recorder is None:
                raise ValueError('speed execution requires mode=melody and record=true')
            if not values['midi_input'].strip():
                raise ValueError('speed execution requires an exact midi_input name')
            self._run_dir = self._recorder.path
            self._capture = midi_factory(values['midi_input'])
            if not self._record_event('benchmark_configuration', **self._benchmark_config):
                raise ValueError('cannot record benchmark configuration: ' + self._record_error)
            self.destroy_timer(self._timer)
            self._timer = self.create_timer(0.005, self._tick, clock=self._timer_clock)
            self._publish_status({'phase': 'waiting', 'note_index': 0,
                                  'target_pose': None, 'sent_at': None,
                                  'reason': '', 'done': False})
        except Exception as error:
            self._failed = True
            self._status.update(phase='failed', reason=str(error), done=True)
            self._finished = True
            self.destroy_node()
            raise

    def _publish_status(self, status):
        self._status = dict(status)
        if not self._speed_initialized:
            return
        payload = {**status, 'benchmark': self._benchmark_config,
                   'progress_means': 'position_commands_and_observed_midi',
                   'sent_at_clock': 'host_monotonic_seconds'}
        if self._run_dir is not None:
            payload['recording_dir'] = str(self._run_dir)
        if self._judge is not None:
            payload['trial'] = {'target_rate_hz': self._trial_rate,
                                'round': self._trial_round}
        self._record_event('status', status=payload)
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        self.status_publisher.publish(String(data=serialized))
        self.get_logger().info(serialized)

    def _send_pose(self, pose, phase, note_index=0):
        self._playback.status.update(
            phase=phase, target_pose=pose, note_index=note_index,
            sent_at=time.monotonic(), reason='', done=False)
        self._dispatch([{'pose': pose, 'note_index': note_index}])

    def _health_reason(self, now):
        if self._capture is not None and self._capture.error:
            return 'MIDI capture failed: ' + self._capture.error
        return super()._health_reason(now)

    def _written(self, message):
        if (self.done or self._pending_stamp is None or
                not self._source_matches(self._written_topic)):
            return
        stamp = (message.header.stamp.sec, message.header.stamp.nanosec)
        if (stamp != self._pending_stamp or
                list(message.position) != self._poses[self._playback.status['target_pose']]):
            return
        now = time.monotonic()
        if not self._record_event(
                'write_ack', command_stamp={'sec': stamp[0], 'nanosec': stamp[1]},
                note_index=self._playback.status['note_index'],
                target_pose=self._playback.status['target_pose'],
                ack_latency_sec=now - self._pending_since):
            self._fail('recording failed: ' + self._record_error)
            return
        event_index = self._pending_event
        self._pending_stamp = None
        self._pending_event = None
        self._written_at = now
        if event_index is not None and not self._ending:
            try:
                self._judge.record_command_ack(event_index, now)
            except BenchmarkFailure as error:
                self._abort_benchmark(str(error))
                return
        elif self._trial_due is None and not self._ending:
            self._trial_due = now + self._benchmark_config['ready_settle']
        self._sync_status()

    def _consume_midi(self):
        if self._capture is None:
            return
        events = self._capture.drain()
        if self._capture.error:
            # Preserve queued evidence, but an input fault cannot trigger a cleanup move.
            self._fail('MIDI capture failed: ' + self._capture.error)
        for event in events:
            if not self._record_event('midi', **event):
                self._fail('recording failed: ' + self._record_error)
                return
            if self._ending or (self.done and self._status.get('phase') != 'completed'):
                continue
            if event['type'] == 'sustain':
                if event['value'] >= 64:
                    self._abort_benchmark('sustain pedal must be released during the test')
                continue
            if self._judge is None:
                self._abort_benchmark('unsolicited MIDI before the first trial; release all keys')
                continue
            try:
                match = self._judge.accept_midi(
                    event['type'], event['note'], event['monotonic_ns'] / 1e9,
                    event['velocity'])
                self._record_event('midi_match', match=match)
            except BenchmarkFailure as error:
                self._abort_benchmark(str(error))
        if self._capture.error:
            self._fail('MIDI capture failed: ' + self._capture.error)

    def _save_trial(self, reason='', failure_type=''):
        if self._judge is None:
            return
        summary = {**self._judge.report(), 'round': self._trial_round}
        if reason:
            summary.update(passed=False, reason=reason,
                           failure_type=summary['failure_type'] or failure_type)
        if self._trial_saved:
            self._trial_results[-1] = summary
        else:
            self._trial_results.append(summary)
            self._trial_saved = True
        self._record_event('trial_result', **summary)

    def _abort_benchmark(self, reason):
        if self._ending:
            return
        if self._capture is not None and self._capture.error:
            self._fail('MIDI capture failed: ' + self._capture.error)
            return
        self._save_trial(reason, 'benchmark')
        if self.done or self._destroyed:
            self._fail(reason)
            return
        health = self._health_reason(time.monotonic()) if self._started else ''
        if health:
            self._fail(reason + '; no release: ' + health)
            return
        self._ending = True
        self._end_phase, self._end_reason = 'failed', reason
        self._failed = True
        self._advance_end()

    def _fail(self, reason):
        # Transport/recording faults never issue another position command.
        if not self._trial_closed:
            self._save_trial(reason, 'communication_or_recording')
        self._ending = True
        self._failed = True
        self._finished = True
        if self._playback is not None:
            self._playback.fail(reason)
        self._publish_status({**self._status, 'phase': 'failed', 'reason': reason, 'done': True})

    def _advance_end(self):
        if self._pending_stamp is not None:
            return
        reason = self._health_reason(time.monotonic()) if self._started else ''
        if reason:
            self._fail('stop without release: ' + reason)
            return
        if (self._started and not self._release_sent and
                self._playback.status.get('target_pose') != 'READY'):
            self._release_sent = True
            self._pending_event = None
            self._send_pose('READY', 'stopping')
            return
        self._finish(self._end_phase, self._end_reason)

    def _finish(self, phase, reason=''):
        self._finished = True
        self._failed = phase == 'failed'
        if self._playback is not None:
            self._playback.status.update(phase=phase, reason=reason, done=True)
        self._publish_status({**self._status, 'phase': phase, 'reason': reason, 'done': True})

    def _begin_trial(self, now):
        config = self._benchmark_config
        self._trial_rate = self._rates[self._rate_index]
        self._trial_round = self._round_index + 1
        self._score = make_score(config['pattern'], self._trial_rate,
                                 config['notes_per_trial'], now + 0.05)
        self._judge = MidiJudge(self._score)
        self._trial_closed = False
        self._trial_saved = False
        self._next_event = 0
        self._record_event('trial_started', rate=self._trial_rate,
                           round=self._trial_round, score=self._score)

    def _tick(self):
        if not self._speed_initialized or self.done:
            return
        self._consume_midi()
        if self.done:
            return
        now = time.monotonic()
        reason = self._health_reason(now)
        if not self._started:
            if self._ending:
                self._advance_end()
            elif now - self._wait_started >= 10:
                self._fail('right-hand readiness timed out after 10 s: ' + reason)
            elif not reason:
                self._started = True
                self._send_pose('READY', 'settling')
            return
        if reason:
            self._fail(reason)
            return
        if self._pending_stamp is not None and now - self._pending_since > 0.5:
            self._fail('right-hand position write confirmation timed out (>0.5 s)')
            return
        if self._ending:
            self._advance_end()
            return
        # Endpoint discovery above can block; never authorize using its old timestamp.
        now = time.monotonic()
        if self._trial_closed:
            if self._trial_due is None or now < self._trial_due:
                return
            if self._rate_index >= len(self._rates):
                self._finish('completed')
                return
            self._begin_trial(now)
        try:
            now = time.monotonic()
            self._judge.check_timeout(now)
            if self._pending_stamp is not None:
                return
            if self._next_event < len(self._score):
                event = self._score[self._next_event]
                if now < event['planned_at']:
                    return
                self._judge.note_command_sent(self._next_event, time.monotonic())
                self._pending_event = self._next_event
                self._next_event += 1
                self._send_pose(event['pose'], 'pressing' if event['type'] == 'on'
                                else 'releasing', event['note_index'])
            elif self._judge.done:
                self._judge.finish()
                self._save_trial()
                self._trial_closed = True
                self._trial_due = now + max(self._benchmark_config['trial_rest'],
                                            self._score[-1]['period'] / 2)
                self._round_index += 1
                if self._round_index == self._benchmark_config['repeats']:
                    self._rate_index += 1
                    self._round_index = 0
                self._publish_status({**self._status, 'phase': 'resting', 'done': False})
        except BenchmarkFailure as error:
            self._abort_benchmark(str(error))

    def _stop(self, request, response):
        self._record_event('stop_requested')
        if not self.done and not self._ending:
            self._stop_requested = True
            reason = self._health_reason(time.monotonic()) if self._started else ''
            if not self._trial_closed:
                self._save_trial('actively stopped', 'stopped')
            if reason:
                self._fail('stop without release: ' + reason)
            else:
                self._ending = True
                self._end_phase, self._end_reason = 'stopped', 'actively stopped'
                self._advance_end()
        response.success = True
        response.message = ('No further notes; at most one READY while communication is healthy. '
                            'This is not a mechanical emergency stop.')
        return response

    def _report(self):
        passed = []
        for rate in self._rates:
            trials = [entry for entry in self._trial_results if entry['target_rate_hz'] == rate]
            if (len(trials) == self._benchmark_config['repeats'] and
                    all(entry['passed'] for entry in trials)):
                passed.append(rate)
        return {
            'schema_version': 1,
            'outcome': ('interrupted' if self._status.get('phase') == 'interrupted' else
                        'failed' if self.failed else self._status.get('phase', 'interrupted')),
            'reason': self._record_error or self._status.get('reason', ''),
            'configuration': self._benchmark_config,
            'trials': self._trial_results,
            'highest_passed_rate_hz': (
                max(passed) if passed and not self._record_error else None),
            'scope': 'Measured host command/RS485/MIDI chain; not an absolute L20 motor limit.',
            'clock': 'Host monotonic MIDI callback receipt; not calibrated acoustic onset.',
        }

    def destroy_node(self):
        """Drain MIDI and reconcile raw serial records before finalizing the report."""
        if self._destroyed:
            return
        self._destroyed = True
        if self._capture is not None:
            self._capture.close()
            self._consume_midi()
        if not self.done:
            if not self._trial_closed:
                self._save_trial('process interrupted', 'interrupted')
            self._status.update(phase='interrupted', reason='process interrupted')
            self._failed = True
        # The base closes the recording and can still discover missing serial writes.
        recorder = self._recorder
        result = super().destroy_node()
        if recorder is not None and recorder.error:
            self._record_error = self._record_error or recorder.error
            self._failed = True
        if self._run_dir is not None:
            temporary = self._run_dir / '.speed_report.json.tmp'
            try:
                with temporary.open('w', encoding='utf-8') as stream:
                    json.dump(self._report(), stream, ensure_ascii=False,
                              indent=2, allow_nan=False)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._run_dir / 'speed_report.json')
            except (OSError, ValueError) as error:
                self._failed = True
                self._record_error = 'speed report write failed: ' + str(error)
                print(self._record_error, flush=True)
        return result


def main(args=None):
    """Run the benchmark without ever opening an arm or MIDI output port."""
    rclpy.init(args=args)
    node = None
    executor = SingleThreadedExecutor()
    result = 0
    try:
        node = SpeedTestNode()
        executor.add_node(node)
        while rclpy.ok() and not node.done:
            executor.spin_once(timeout_sec=0.01)
        until = time.monotonic() + 0.2
        while rclpy.ok() and time.monotonic() < until:
            executor.spin_once(timeout_sec=0.01)
    except (KeyboardInterrupt, ExternalShutdownException):
        result = 1
    finally:
        executor.shutdown()
        if node is not None:
            node.destroy_node()
            result = 1 if node.failed else result
        if rclpy.ok():
            rclpy.shutdown()
    return result
