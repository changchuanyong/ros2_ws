"""Exercise the ROS hand interface with fake serial hardware only."""

import math
import time
from types import SimpleNamespace

import pytest

rclpy = pytest.importorskip('rclpy')
from rclpy.context import Context  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.impl.implementation_singleton import rclpy_implementation as _rclpy  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402

from rm_l20_driver import node as driver  # noqa: E402
from rm_l20_driver import discovery  # noqa: E402


class FakeHand:
    """Record commands and inject feedback/transport errors without a port."""

    def __init__(self, **kwargs):
        self.connection = kwargs
        self.commands = []
        self.positions = list(range(20))
        self.speeds = list(range(20, 40))
        self.reads = 0
        self.close_count = 0
        self.write_error = None
        self.read_error = None
        self.speed_error = None
        self.close_error = None

    def set_joint_positions(self, values):
        if self.write_error:
            raise self.write_error
        self.commands.append(list(values))

    def read_uid_registers(self):
        return [ord('T') | ord('E') << 8, ord('S') | ord('T') << 8] + [0] * 9

    def get_state(self):
        self.reads += 1
        if self.read_error:
            raise self.read_error
        return self.positions

    def get_speed(self):
        if self.speed_error:
            raise self.speed_error
        return self.speeds

    def close(self):
        self.close_count += 1
        if self.close_error:
            raise self.close_error


@pytest.fixture
def make_node(monkeypatch):
    """Give each test an isolated ROS context and a fake protocol factory."""
    monkeypatch.setenv('ROS_DOMAIN_ID', '219')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    context = Context()
    rclpy.init(context=context)
    monkeypatch.setattr(discovery, 'device_key', lambda port: port)
    monkeypatch.setattr(discovery, 'open_hand', lambda port, baudrate, slave_id: FakeHand(
        modbus_port=port, baudrate=baudrate, hand_id=slave_id))
    nodes = []

    def create(**params):
        params.setdefault('expected_uid', 'TEST')
        node = driver.L20RS485Driver(
            context=context,
            parameter_overrides=[Parameter(key, value=value) for key, value in params.items()])
        nodes.append(node)
        state_messages, abort_messages = [], []
        monkeypatch.setattr(node.state_publisher, 'publish', state_messages.append)
        monkeypatch.setattr(node.abort_publisher, 'publish', abort_messages.append)
        return node, node._hand, state_messages, abort_messages

    yield create
    for node in nodes:
        if node._timer is not None:
            node.destroy_node()
    if context.ok():
        context.shutdown()


@pytest.mark.parametrize('side,port', [('left', '/dev/ttyUSB0'), ('right', '/dev/ttyUSB1')])
def test_topics_connection_and_no_startup_motion(make_node, side, port):
    node, hand, _, _ = make_node(hand_type=side, modbus=port, slave_id=7)
    assert node.command_subscription.topic_name == f'/cb_{side}_hand_control_cmd'
    assert node.state_publisher.topic_name == f'/cb_{side}_hand_state'
    assert hand.connection == {'hand_id': 7, 'modbus_port': port, 'baudrate': 115200}
    assert hand.commands == []
    assert hand.reads == 1
    assert node._timer.timer_period_ns == 50_000_000


@pytest.mark.parametrize('model', ['L20-10', 'L20-11'])
def test_both_rs485_model_names(make_node, model):
    node, hand, _, _ = make_node(hand_joint=model)
    assert hand is not None
    assert not node._faulted


@pytest.mark.parametrize('params', [
    {'hand_type': 'both'}, {'hand_joint': 'L20'}, {'modbus': ''},
    {'baudrate': 0}, {'slave_id': 0}, {'slave_id': 248},
    {'poll_rate': 0.0}, {'poll_rate': math.nan}, {'poll_rate': 101.0},
    {'expected_uid': ''}, {'expected_uid': ' '},
])
def test_bad_parameters_rejected_before_serial_open(make_node, monkeypatch, params):
    def forbidden_open(*args, **kwargs):
        pytest.fail('invalid parameters opened a serial connection')
    monkeypatch.setattr(discovery, 'open_hand', forbidden_open)
    with pytest.raises(ValueError):
        make_node(**params)


def test_raw_position_command_preserves_sdk_order(make_node):
    node, hand, _, _ = make_node()
    pose = [float(index * 10) for index in range(20)]
    pose[0], pose[-1] = 0.0, 255.0
    node.command_callback(JointState(position=pose))
    assert hand.commands == [pose]


def test_wrong_uid_closes_before_state_or_commands(make_node, monkeypatch):
    hand = FakeHand()
    monkeypatch.setattr(discovery, 'open_hand', lambda *args: hand)
    node, _, _, _ = make_node(expected_uid='OTHER')
    node.command_callback(JointState(position=[0.0] * 20))
    assert node._faulted and hand.close_count == 1
    assert node.command_subscription is None
    assert hand.reads == 0 and hand.commands == []


@pytest.mark.parametrize('pose', [
    [], [0.0] * 19, [0.0] * 21,
    [math.nan] + [0.0] * 19, [math.inf] + [0.0] * 19,
    [-1.0] + [0.0] * 19, [256.0] + [0.0] * 19,
])
def test_invalid_position_never_reaches_serial(make_node, pose):
    node, hand, _, aborts = make_node()
    node.command_callback(JointState(position=pose))
    assert hand.commands == []
    assert not node._faulted
    assert aborts == []


def test_feedback_matches_sdk_fields_and_is_fresh(make_node):
    node, hand, states, _ = make_node()
    node.poll_state()
    assert len(states) == 1
    assert list(states[0].name) == list(driver.KEYS)
    assert list(states[0].position) == hand.positions
    assert list(states[0].velocity) == hand.speeds
    assert list(states[0].effort) == [0.0] * 20
    hand.positions = [255] * 20
    node.poll_state()
    assert list(states[-1].position) == [255.0] * 20
    assert hand.commands == []


def test_uint16_feedback_is_not_clipped_to_command_range(make_node):
    node, hand, states, aborts = make_node()
    hand.positions[11:15] = [65535] * 4
    hand.speeds = [256, 1024, 65535] + [0] * 17
    node.poll_state()
    assert list(states[0].position) == hand.positions
    assert list(states[0].velocity) == hand.speeds
    assert not node._faulted
    assert aborts == []


@pytest.mark.parametrize('field', ['positions', 'speeds'])
@pytest.mark.parametrize('value', [-1, 65536, math.nan, math.inf])
def test_invalid_feedback_is_not_published(make_node, field, value):
    node, hand, states, aborts = make_node()
    getattr(hand, field)[0] = value
    node.poll_state()
    assert node._faulted
    assert states == []
    assert len(aborts) == 1 and aborts[0].data


@pytest.mark.parametrize('failure', ['read', 'speed', 'write', 'invalid_state'])
def test_transport_failure_latches_abort_closes_and_stops(make_node, failure):
    node, hand, states, aborts = make_node()
    node.poll_state()
    assert len(states) == 1
    if failure == 'write':
        hand.write_error = OSError('serial unplugged')
        node.command_callback(JointState(position=[128.0] * 20))
    else:
        if failure == 'read':
            hand.read_error = OSError('serial unplugged')
        elif failure == 'speed':
            hand.speed_error = RuntimeError('Modbus exception')
        else:
            hand.positions = [0] * 19
        node.poll_state()
    assert node._faulted
    assert node._timer.is_canceled()
    assert node._abort_timer.timer_period_ns == 500_000_000
    assert not node._abort_timer.is_canceled()
    assert node._hand is None
    assert hand.close_count == 1
    assert len(aborts) == 1 and aborts[0].data
    reads = hand.reads
    node.command_callback(JointState(position=[0.0] * 20))
    node.poll_state()
    assert hand.commands == []
    assert hand.reads == reads
    assert len(states) == 1
    assert len(aborts) == 1


def test_shutdown_closes_without_motion(make_node):
    node, hand, _, _ = make_node()
    node.destroy_node()
    assert hand.close_count == 1
    assert hand.commands == []


def test_close_error_does_not_skip_abort_or_resume_commands(make_node):
    node, hand, _, aborts = make_node()
    hand.close_error = OSError('adapter removed')
    hand.read_error = OSError('no response')
    node.poll_state()
    assert node._faulted
    assert node._hand is None
    assert hand.close_count == 1
    assert len(aborts) == 1 and aborts[0].data
    node.command_callback(JointState(position=[128.0] * 20))
    assert hand.commands == []


def test_connect_failure_stays_faulted(make_node, monkeypatch):
    def failed_open(*args, **kwargs):
        raise ConnectionError('no serial adapter')
    monkeypatch.setattr(discovery, 'open_hand', failed_open)
    node, hand, states, _ = make_node()
    assert hand is None
    assert node._faulted
    assert node._timer.is_canceled()
    node.command_callback(JointState(position=[0.0] * 20))
    node.poll_state()
    assert states == []


def test_late_volatile_subscriber_receives_repeated_fault(make_node, monkeypatch):
    node, hand, _, _ = make_node()
    publisher = node.abort_publisher
    monkeypatch.setattr(publisher, 'publish', type(publisher).publish.__get__(publisher))
    hand.read_error = OSError('serial disconnected before player startup')
    node.poll_state()

    # Match the existing player's default reliable, volatile subscription.
    received = []
    observer = Node('late_fault_observer', context=node.context)
    observer.create_subscription(Bool, '/robopianist/feedback_abort', received.append, 10)
    executor = SingleThreadedExecutor(context=node.context)
    executor.add_node(node)
    executor.add_node(observer)
    try:
        deadline = time.monotonic() + 4.0
        while len(received) < 2 and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.1)
        assert len(received) >= 2
        assert all(message.data for message in received)
        assert hand.close_count == 1
        assert hand.commands == []
    finally:
        executor.shutdown()
        observer.destroy_node()


def test_fault_shutdown_disposes_both_timers(make_node):
    node, hand, _, _ = make_node()
    hand.read_error = OSError('serial disconnected')
    node.poll_state()
    node.destroy_node()
    assert node._timer is None
    assert node._abort_timer is None
    assert node._ready_timer is None
    assert hand.close_count == 1


def test_right_auto_keeps_the_discovered_connection(make_node, monkeypatch):
    hand = FakeHand()
    opened = []
    monkeypatch.setattr(discovery.list_ports, 'comports', lambda: [
        SimpleNamespace(device='/fake/right', vid=0x1A86, pid=0x7523)])

    def open_once(port, baudrate, slave_id):
        opened.append(port)
        return hand

    monkeypatch.setattr(discovery, 'open_hand', open_once)
    node, connection, _, _ = make_node(hand_type='right', modbus='auto')
    assert connection is hand and opened == ['/fake/right']
    assert node.command_subscription.topic_name == '/cb_right_hand_control_cmd'
    assert hand.commands == [] and hand.reads == 1


def test_private_ready_requires_fresh_state_and_command_gate(make_node, monkeypatch):
    node, hand, _, _ = make_node(hand_type='right')
    ready = []
    monkeypatch.setattr(node.ready_publisher, 'publish', lambda msg: ready.append(msg.data))
    assert node.ready_publisher.topic_name == '/l20_rs485_driver/ready'
    assert node._ready_timer.timer_period_ns == 100_000_000
    assert node.ready_publisher.qos_profile.durability == driver.DurabilityPolicy.VOLATILE
    node.publish_ready()
    assert ready[-1] is True
    node._command_gate = lambda: False
    node.publish_ready()
    assert ready[-1] is False
    node._command_gate = lambda: True
    node._last_state_time = time.monotonic() - 0.6
    node.publish_ready()
    assert ready[-1] is False
    node.poll_state()
    node.publish_ready()
    assert ready[-1] is True
    hand.read_error = OSError('disconnected')
    node.poll_state()
    assert ready[-1] is False
    node.publish_ready()
    assert ready[-1] is False


def test_shutdown_publishes_not_ready_without_position_write(make_node, monkeypatch):
    node, hand, _, _ = make_node(hand_type='right')
    ready = []
    monkeypatch.setattr(node.ready_publisher, 'publish', lambda msg: ready.append(msg.data))
    node.destroy_node()
    assert ready == [False]
    assert node._ready_timer is None and hand.commands == []


def test_command_written_preserves_original_message_after_serial_ack(make_node, monkeypatch):
    node, hand, _, _ = make_node(hand_type='right')
    message = JointState(position=[float(index) for index in range(20)])
    message.header.stamp = node.get_clock().now().to_msg()
    message.header.frame_id = 'command_correlation'
    acknowledgements = []

    def acknowledged(value):
        assert hand.commands == [list(message.position)]
        acknowledgements.append(value)

    monkeypatch.setattr(node.command_written_publisher, 'publish', acknowledged)
    assert node.command_written_publisher.topic_name == '/l20_rs485_driver/command_written'
    node.command_callback(message)
    assert acknowledgements == [message] and acknowledgements[0] is message


@pytest.mark.parametrize('failure', ['write', 'invalid', 'gate', 'faulted'])
def test_rejected_or_failed_command_has_no_written_ack(make_node, monkeypatch, failure):
    node, hand, _, _ = make_node(hand_type='right')
    acknowledgements = []
    monkeypatch.setattr(node.command_written_publisher, 'publish', acknowledgements.append)
    message = JointState(position=[128.0] * 20)
    if failure == 'write':
        hand.write_error = OSError('serial write rejected')
    elif failure == 'invalid':
        message.position = [math.nan] * 20
    elif failure == 'gate':
        node._command_gate = lambda: False
    else:
        node._enter_fault('injected fault')
    node.command_callback(message)
    assert acknowledgements == [] and hand.commands == []


def test_shutdown_during_ready_publish_still_closes_serial(make_node, monkeypatch):
    node, hand, _, _ = make_node(hand_type='right')
    publish = node.ready_publisher.publish

    def shutdown_then_publish(message):
        assert node.context.ok()  # destroy_node's initial context check already passed.
        node.context.shutdown()
        publish(message)

    monkeypatch.setattr(node.ready_publisher, 'publish', shutdown_then_publish)
    node.destroy_node()
    assert hand.close_count == 1 and hand.commands == []
    assert node._timer is None and node._ready_timer is None


def test_ready_publish_error_with_live_context_is_not_suppressed(make_node, monkeypatch):
    node, _, _, _ = make_node()

    def failed_publish(message):
        raise _rclpy.RCLError('injected publisher failure with a live context')

    with monkeypatch.context() as patch:
        patch.setattr(node.ready_publisher, 'publish', failed_publish)
        with pytest.raises(_rclpy.RCLError, match='injected publisher failure'):
            node.publish_ready()
    assert node.context.ok()


@pytest.mark.parametrize('shutdown_context', [False, True])
def test_main_cleans_up_callback_publish_race_only_after_shutdown(monkeypatch, shutdown_context):
    monkeypatch.setenv('ROS_DOMAIN_ID', '219')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    cleanup = []
    monkeypatch.setattr(driver, 'L20RS485Driver', lambda: SimpleNamespace(
        destroy_node=lambda: cleanup.append('serial_closed')))

    class InterruptedExecutor:
        def add_node(self, node):
            pass

        def spin(self):
            if shutdown_context:
                rclpy.shutdown()
            raise _rclpy.RCLError('injected callback publish failure')

        def shutdown(self):
            cleanup.append('executor_stopped')

    monkeypatch.setattr(driver, 'SingleThreadedExecutor', InterruptedExecutor)
    if shutdown_context:
        driver.main(args=[])
    else:
        with pytest.raises(_rclpy.RCLError, match='injected callback publish failure'):
            driver.main(args=[])
    assert cleanup == ['executor_stopped', 'serial_closed']
    assert not rclpy.ok()
