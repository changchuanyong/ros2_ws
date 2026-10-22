"""Right-hand position playback; progress is not evidence of a sounding key."""

import json
import math
import os
import time

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger

from rm_piano_player.single_hand_core import (
    MELODY, Playback, calibration_report, load_pose_config, validate_execution,
)


def playback_parameters(mode, pose, press_duration, release_duration, ready_settle):
    """Check options even for an offline preview with empty calibration."""
    if mode not in ('pose_test', 'melody'):
        raise ValueError('mode must be pose_test or melody')
    if pose not in ('READY', 'PRESS_C', 'PRESS_D', 'PRESS_E', 'PRESS_F', 'PRESS_G'):
        raise ValueError('pose must be READY or PRESS_C through PRESS_G')
    for name, value in (
            ('press_duration', press_duration), ('release_duration', release_duration),
            ('ready_settle', ready_settle)):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be finite and positive')


def preview_schedule(mode, pose, press_duration, release_duration, ready_settle):
    """List earliest sends; actual execution never catches up after a delay."""
    schedule = [{'at': 0.0, 'pose': 'READY', 'note_index': 0}]
    notes = MELODY if mode == 'melody' else (() if pose == 'READY' else (pose[6:],))
    at = ready_settle
    for index, note in enumerate(notes, 1):
        schedule.append({'at': at, 'pose': 'PRESS_' + note, 'note_index': index})
        at += press_duration
        schedule.append({'at': at, 'pose': 'READY', 'note_index': index})
        at += release_duration
    return schedule


class SingleHandPiano(Node):
    """Gate every timed action on this run's driver and fresh right-hand state."""

    def __init__(self, **kwargs):
        super().__init__('single_hand_piano', **kwargs)
        self._finished = False
        self._failed = False
        self._started = False
        self._last_state = None
        self._last_ready = None
        self._ready = False
        self._playback = None
        self._pending_stamp = None
        self._pending_since = None
        self._hold_until = 0.0
        self._written_at = None
        self._stop_requested = False
        self._status = {}
        self.command_publisher = None
        self._timer = None
        self._timer_clock = Clock(clock_type=ClockType.STEADY_TIME)
        durable = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status_publisher = self.create_publisher(
            String, '/single_hand_piano/status', durable)
        self.create_service(Trigger, '/single_hand_piano/stop', self._stop)
        try:
            default_config = os.path.join(get_package_share_directory('rm_piano_player'),
                                          'config', 'right_hand_ode_to_joy.yaml')
            defaults = {
                'execute': False, 'mode': 'pose_test', 'pose': 'READY',
                'pose_config': default_config, 'press_duration': 0.5,
                'release_duration': 0.5, 'ready_settle': 1.0,
                'driver_node': '', 'ready_topic': '', 'fault_topic': '', 'written_topic': '',
            }
            for name, value in defaults.items():
                self.declare_parameter(name, value)
            values = {name: self.get_parameter(name).value for name in defaults}
            options = {name: values[name] for name in (
                'mode', 'pose', 'press_duration', 'release_duration', 'ready_settle')}
            playback_parameters(**options)
            config = load_pose_config(values['pose_config'])
            report = calibration_report(config)
            schedule = preview_schedule(**options)
            if not values['execute']:
                self._publish_status({
                    'phase': 'dry_run', 'note_index': 0, 'target_pose': None,
                    'sent_at': None, 'reason': '', 'done': True,
                    'calibration': report, 'schedule': schedule,
                    'melody': list(MELODY), 'execute': False,
                })
                self._finished = True
                return
            self._poses = validate_execution(config, values['mode'], values['pose'])
            self._driver_node = values['driver_node']
            self._ready_topic = values['ready_topic']
            self._fault_topic = values['fault_topic']
            self._written_topic = values['written_topic']
            channels = (self._ready_topic, self._fault_topic, self._written_topic)
            if (not self._driver_node or any(not topic.startswith('/') for topic in channels) or
                    len(set(channels)) != len(channels)):
                raise ValueError('execute requires this launch\'s driver_node, ready_topic '
                                 'fault_topic and written_topic; '
                                 'use l20_right_hand_piano.launch.py')
            self._playback = Playback(self._poses, **options)
            self.command_publisher = self.create_publisher(
                JointState, '/cb_right_hand_control_cmd', 10)
            self.create_subscription(JointState, '/cb_right_hand_state', self._state, 1)
            self.create_subscription(Bool, self._ready_topic, self._readiness, 1)
            self.create_subscription(Bool, self._fault_topic, self._fault, durable)
            self.create_subscription(JointState, self._written_topic, self._written, 1)
            self._wait_started = time.monotonic()
            self._publish_status({'phase': 'waiting', 'note_index': 0, 'target_pose': None,
                                  'sent_at': None, 'reason': '', 'done': False})
            self._timer = self.create_timer(0.02, self._tick, clock=self._timer_clock)
        except Exception:
            super().destroy_node()
            raise

    @property
    def done(self):
        return self._finished

    @property
    def failed(self):
        return self._failed

    def _is_driver(self, endpoint):
        return endpoint.node_name == self._driver_node and endpoint.node_namespace == '/'

    def _source_matches(self, topic):
        # Humble callbacks do not expose MessageInfo on all supported releases.
        # Require a single publisher with this run's unique driver name instead.
        endpoints = self.get_publishers_info_by_topic(topic)
        return len(endpoints) == 1 and self._is_driver(endpoints[0])

    def _state(self, message):
        if self.done or not self._source_matches('/cb_right_hand_state'):
            return
        if (len(message.position) != 20 or
                any(not math.isfinite(v) or not 0 <= v <= 65535 for v in message.position)):
            self._fail('invalid right-hand feedback')
            return
        stamp = message.header.stamp.sec + message.header.stamp.nanosec / 1e9
        age = self.get_clock().now().nanoseconds / 1e9 - stamp
        if stamp <= 0 or not 0 <= age <= 0.5:
            if self._started:
                self._fail('right-hand state timestamp is stale or invalid')
            return
        self._last_state = time.monotonic() - age

    def _readiness(self, message):
        if self.done or not self._source_matches(self._ready_topic):
            return
        self._ready = message.data
        self._last_ready = time.monotonic()
        if self._started and not self._ready:
            self._fail('right-hand driver lost readiness')

    def _fault(self, message):
        if not self.done and message.data and self._source_matches(self._fault_topic):
            self._fail('right-hand driver reported a fault')

    def _written(self, message):
        if (self.done or self._pending_stamp is None or
                not self._source_matches(self._written_topic)):
            return
        stamp = (message.header.stamp.sec, message.header.stamp.nanosec)
        if (stamp != self._pending_stamp or
                list(message.position) != self._poses[self._playback.status['target_pose']]):
            return
        self._pending_stamp = None
        self._written_at = time.monotonic()
        durations = {'settling': self._playback.ready_settle,
                     'pressing': self._playback.press_duration,
                     'releasing': self._playback.release_duration}
        self._hold_until = self._written_at + durations.get(self._playback.status['phase'], 0.0)
        self._sync_status()

    def _health_reason(self, now):
        if not self._ready:
            return 'right-hand driver is not ready'
        if self._last_ready is None or now - self._last_ready > 0.5:
            return 'right-hand readiness heartbeat expired (>0.5 s)'
        if self._last_state is None or now - self._last_state > 0.5:
            return 'right-hand state expired (>0.5 s)'
        states = self.get_publishers_info_by_topic('/cb_right_hand_state')
        commands = self.get_subscriptions_info_by_topic('/cb_right_hand_control_cmd')
        if len(states) != 1 or not self._is_driver(states[0]):
            return 'right-hand state publisher is absent or ambiguous'
        if len(commands) != 1 or not self._is_driver(commands[0]):
            return 'right-hand command subscription is absent or ambiguous'
        if self.command_publisher.get_subscription_count() != 1:
            return 'right-hand command subscription is not connected'
        if not self._source_matches(self._written_topic):
            return 'right-hand write confirmation publisher is absent or ambiguous'
        return ''

    def _tick(self):
        if self.done:
            return
        now = time.monotonic()
        reason = self._health_reason(now)
        if not self._started:
            if now - self._wait_started >= 10.0:
                self._fail('right-hand readiness timed out after 10 s: ' + reason)
            elif not reason:
                self._started = True
                self._dispatch(self._playback.start(now))
            return
        if reason:
            self._fail(reason)
            return
        if self._pending_stamp is not None:
            if now - self._pending_since > 0.5:
                self._fail('right-hand position write confirmation timed out (>0.5 s)')
            return
        if self._stop_requested:
            self._dispatch(self._playback.stop(now, healthy=True))
            return
        if now < self._hold_until:
            return
        self._dispatch(self._playback.tick(now))

    def _dispatch(self, commands):
        for command in commands:
            message = JointState()
            message.header.stamp = self.get_clock().now().to_msg()
            message.position = self._poses[command['pose']]
            self._pending_stamp = (message.header.stamp.sec, message.header.stamp.nanosec)
            self._pending_since = time.monotonic()
            self._written_at = None
            self.command_publisher.publish(message)
        self._sync_status()

    def _sync_status(self):
        status = {**self._playback.status, 'awaiting_write': self._pending_stamp is not None,
                  'written_at': self._written_at, 'stop_requested': self._stop_requested}
        if self._pending_stamp is not None:
            status['done'] = False
            if self._stop_requested:
                status['phase'] = 'stopping'
        if status != self._status:
            self._publish_status(status)
        if self._playback.done and self._pending_stamp is None:
            self._finished = True

    def _publish_status(self, status):
        self._status = dict(status)
        payload = {**status, 'progress_means': 'position_commands_only',
                   'sent_at_clock': 'monotonic_seconds'}
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        self.status_publisher.publish(String(data=serialized))
        self.get_logger().info(serialized)

    def _fail(self, reason):
        if self.done:
            return
        if self._playback is not None:
            self._playback.fail(reason)
        self._failed = True
        self._finished = True
        self._publish_status({**self._status, 'phase': 'failed', 'reason': reason, 'done': True})

    def _stop(self, request, response):
        if self.done:
            response.success = True
            response.message = 'Playback already ended; no command sent.'
            return response
        now = time.monotonic()
        reason = self._health_reason(now)
        if self._started and reason:
            self._fail('stop without release: ' + reason)
        elif self._started:
            self._stop_requested = True
            self._tick()
            if not self.done:
                self._sync_status()
        else:
            self._finished = True
            self._publish_status({**self._status, 'phase': 'stopped',
                                  'reason': 'stopped before readiness', 'done': True})
        response.success = True
        response.message = ('Stop requested; no further notes. ' +
                            ('No release sent: ' + reason if reason else
                             'At most one READY after the current write is confirmed; '
                             'this is not a mechanical stop.'))
        return response


def main(args=None):
    rclpy.init(args=args)
    node = None
    executor = SingleThreadedExecutor()
    result = 0
    try:
        node = SingleHandPiano()
        executor.add_node(node)
        while rclpy.ok() and not node.done:
            executor.spin_once(timeout_sec=0.05)
        result = 1 if node.failed else 0
        # Allow the final status/READY to leave DDS before launch stops the driver.
        until = time.monotonic() + 0.2
        while rclpy.ok() and time.monotonic() < until:
            executor.spin_once(timeout_sec=0.02)
    except (KeyboardInterrupt, ExternalShutdownException):
        # A killed/disconnected process cannot promise an automatic release.
        pass
    finally:
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return result
