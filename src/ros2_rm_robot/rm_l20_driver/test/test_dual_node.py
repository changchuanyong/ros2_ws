"""Exercise joint readiness and synchronous peer shutdown using real ROS nodes."""

import pytest

rclpy = pytest.importorskip('rclpy')
from rclpy.context import Context  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402

from rm_l20_driver import dual_node  # noqa: E402
from rm_l20_driver.discovery import HandBinding  # noqa: E402
from rm_l20_driver.wait_ready import wait_until_ready  # noqa: E402
from test_node import FakeHand  # noqa: E402


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setenv('ROS_DOMAIN_ID', '219')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    value = Context()
    rclpy.init(context=value)
    yield value
    value.shutdown()


@pytest.fixture
def pair(context, monkeypatch):
    hands = {side: FakeHand() for side in ('left', 'right')}
    bindings = {side: HandBinding(f'/fake/{side}', side.upper(), hand)
                for side, hand in hands.items()}
    monkeypatch.setattr(dual_node, 'discover_hands', lambda *args, **kwargs: bindings.copy())
    manager = dual_node.DualHandDriver(context=context, parameter_overrides=[
        Parameter('left_hand_uid', value='LEFT'), Parameter('right_hand_uid', value='RIGHT')])
    ready = []
    monkeypatch.setattr(manager.ready_publisher, 'publish', lambda message: ready.append(message.data))
    yield manager, hands, ready
    manager.destroy_node()


def test_both_initial_states_required_and_connections_retained(pair):
    manager, hands, ready = pair
    original = hands['right'].get_state

    def right_initial_read():
        assert manager.ready is False
        assert manager.hands[0].command_subscription is None
        manager.hands[0].command_callback(JointState(position=[128.0] * 20))
        assert hands['left'].commands == []
        return original()

    hands['right'].get_state = right_initial_read
    manager.initialize()
    assert manager.ready and ready == [True]
    assert [node.get_name() for node in manager.hands] == ['left_l20_driver', 'right_l20_driver']
    for node, side in zip(manager.hands, ('left', 'right')):
        assert node._hand is hands[side]
        assert node.command_subscription is not None
        assert hands[side].reads == 1
        assert hands[side].commands == []
        node.command_callback(JointState(position=[128.0] * 20))
        assert hands[side].commands == [[128.0] * 20]


@pytest.mark.parametrize('side', ['left', 'right'])
def test_failed_initial_feedback_never_enables_either_hand(pair, side):
    manager, hands, ready = pair
    hands[side].read_error = OSError('first state unavailable')
    with pytest.raises(RuntimeError, match='initial state'):
        manager.initialize()
    assert manager.faulted and not manager.ready and True not in ready
    for hand in hands.values():
        assert hand.commands == [] and hand.close_count == 1
    for node in manager.hands:
        node.command_callback(JointState(position=[128.0] * 20))
    assert all(hand.commands == [] for hand in hands.values())


@pytest.mark.parametrize('side', ['left', 'right'])
@pytest.mark.parametrize('operation', ['read', 'write'])
def test_any_fault_synchronously_closes_and_disables_both(pair, monkeypatch, side, operation):
    manager, hands, ready = pair
    manager.initialize()
    aborts = []
    for node in manager.hands:
        monkeypatch.setattr(node.abort_publisher, 'publish', lambda msg: aborts.append(msg.data))
    index = 0 if side == 'left' else 1
    if operation == 'read':
        hands[side].read_error = OSError('unplugged')
        manager.hands[index].poll_state()
    else:
        hands[side].write_error = OSError('unplugged')
        manager.hands[index].command_callback(JointState(position=[128.0] * 20))
    assert ready[-1] is False and manager.faulted and not manager.ready
    assert aborts == [True, True]
    for node, hand in zip(manager.hands, hands.values()):
        assert node._faulted and node._hand is None
        assert hand.close_count == 1
        node.command_callback(JointState(position=[128.0] * 20))
        assert hand.commands == []


def test_ready_wait_requires_live_true_and_rejects_retained_true(context):
    node = Node('ready_wait_test', context=context)
    publisher = node.create_publisher(Bool, '/l20/hands_ready', dual_node.ready_qos())
    try:
        publisher.publish(Bool(data=True))
        assert wait_until_ready(node, timeout=0.2) is False
        timer = node.create_timer(0.05, lambda: publisher.publish(Bool(data=False)))
        assert wait_until_ready(node, timeout=0.2) is False
        node.destroy_timer(timer)
        node.create_timer(0.05, lambda: publisher.publish(Bool(data=True)))
        assert wait_until_ready(node, timeout=2.0) is True
    finally:
        node.destroy_node()
