"""Exercise the right-hand player over ROS using only a fake hand driver."""

import json
from pathlib import Path
from types import SimpleNamespace
import time
import uuid

import pytest
import yaml

rclpy = pytest.importorskip('rclpy')
from rclpy.context import Context  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_msgs.msg import Bool, String  # noqa: E402
from std_srvs.srv import Trigger  # noqa: E402

from rm_piano_player import single_hand_node as player_module  # noqa: E402


POSES = ('READY', 'PRESS_C', 'PRESS_D', 'PRESS_E', 'PRESS_F', 'PRESS_G')
MELODY = ('E', 'E', 'F', 'G', 'G', 'F', 'E', 'D', 'C', 'C', 'D', 'E', 'E', 'D', 'D')


class FakeDriver(Node):
    """Publish fresh feedback and record received commands without serial access."""

    def __init__(self, name, ready_topic, fault_topic, written_topic, context):
        super().__init__(name, context=context)
        self.commands = []
        self.command_extras = []
        self.command_messages = []
        self.ready = True
        self.fault = False
        self.emit_state = True
        self.emit_ready = True
        self.emit_written = True
        self.old_state_stamp = False
        self.state = self.create_publisher(JointState, '/cb_right_hand_state', 10)
        self.readiness = self.create_publisher(Bool, ready_topic, 10)
        self.written = self.create_publisher(JointState, written_topic, 10)
        self.abort = self.create_publisher(
            Bool, fault_topic, QoSProfile(
                depth=1, reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.command_subscription = self.create_subscription(
            JointState, '/cb_right_hand_control_cmd', self.receive_command, 10)
        self.create_timer(0.02, self.heartbeat)

    def receive_command(self, message):
        self.commands.append((time.monotonic(), list(message.position)))
        self.command_extras.append((list(message.velocity), list(message.effort)))
        self.command_messages.append(message)
        if self.emit_written:
            self.written.publish(message)

    def heartbeat(self):
        if self.emit_state:
            message = JointState(position=[100.0] * 20)
            message.header.stamp = self.get_clock().now().to_msg()
            if self.old_state_stamp:
                message.header.stamp.sec -= 1
            self.state.publish(message)
        if self.emit_ready:
            self.readiness.publish(Bool(data=self.ready))
        if self.fault:
            self.abort.publish(Bool(data=True))


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Keep every test in a separate context and off the physical ROS domain."""
    monkeypatch.setenv('ROS_DOMAIN_ID', '220')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    monkeypatch.setattr(player_module, 'get_package_share_directory',
                        lambda name: str(Path(__file__).resolve().parents[2] / name))
    context = Context()
    rclpy.init(context=context)
    executor = SingleThreadedExecutor(context=context)
    suffix = uuid.uuid4().hex
    ready_topic = '/single_hand_test/run_' + suffix + '/ready'
    fault_topic = '/single_hand_test/run_' + suffix + '/fault'
    written_topic = '/single_hand_test/run_' + suffix + '/written'
    driver_name = 'test_right_driver_' + suffix
    nodes = []
    config = tmp_path / 'calibrated_test_poses.yaml'
    config.write_text(yaml.safe_dump({'poses': {
        name: {'positions': [float(index + 10)] * 20, 'verified': True}
        for index, name in enumerate(POSES)
    }}))

    def add(node):
        nodes.append(node)
        executor.add_node(node)
        return node

    def fake_driver(**overrides):
        return add(FakeDriver(
            overrides.get('name', driver_name),
            overrides.get('ready_topic', ready_topic),
            overrides.get('fault_topic', fault_topic),
            overrides.get('written_topic', written_topic), context))

    def player(**overrides):
        params = {
            'execute': True, 'mode': 'melody', 'pose': 'READY',
            'pose_config': str(config), 'driver_node': driver_name,
            'ready_topic': ready_topic, 'fault_topic': fault_topic,
            'written_topic': written_topic,
            'press_duration': 0.04, 'release_duration': 0.04, 'ready_settle': 0.04,
        }
        params.update(overrides)
        return add(player_module.SingleHandPiano(
            context=context, parameter_overrides=[
                Parameter(name, value=value) for name, value in params.items()])), params

    def spin_until(predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.01)
        assert predicate(), 'timed out waiting for ROS test condition'

    def spin_for(duration):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.01)

    yield SimpleNamespace(
        context=context, executor=executor, add=add, fake_driver=fake_driver,
        player=player, spin_until=spin_until, spin_for=spin_for, config=config)
    executor.shutdown()
    for node in reversed(nodes):
        node.destroy_node()
    context.shutdown()


def pose_names(driver):
    return [POSES[int(values[0]) - 10] for _, values in driver.commands]


def test_dry_run_has_no_hand_publishers_or_subscriptions(rig):
    template = Path(__file__).resolve().parents[1] / 'config' / 'right_hand_ode_to_joy.yaml'
    driver = rig.fake_driver()
    player, _ = rig.player(execute=False, pose_config=str(template))
    rig.spin_for(0.15)
    assert player.done
    assert driver.commands == []
    publications = player.get_publisher_names_and_types_by_node(
        player.get_name(), player.get_namespace())
    subscriptions = player.get_subscriber_names_and_types_by_node(
        player.get_name(), player.get_namespace())
    assert not any('hand_control_cmd' in topic for topic, _ in publications)
    assert not any('hand_state' in topic for topic, _ in subscriptions)
    assert not any('arm' in topic or 'trajectory' in topic for topic, _ in publications)


def test_right_hand_only_plays_fifteen_notes_and_reports_command_progress(rig):
    driver = rig.fake_driver()
    observer = rig.add(Node('single_hand_status_observer', context=rig.context))
    statuses = []
    observer.create_subscription(
        String, '/single_hand_piano/status', lambda msg: statuses.append(json.loads(msg.data)), 10)
    player, _ = rig.player()
    rig.spin_until(lambda: player.done)
    rig.spin_for(0.08)
    assert not player.failed
    assert pose_names(driver) == ['READY'] + [
        pose for note in MELODY for pose in (f'PRESS_{note}', 'READY')]
    assert len(driver.commands) == 31
    assert statuses
    assert all(fields == ([], []) for fields in driver.command_extras)
    assert all({'phase', 'note_index', 'target_pose', 'sent_at', 'reason'} <= set(status)
               for status in statuses)
    assert all(status['progress_means'] == 'position_commands_only' for status in statuses)
    # A late timer may lengthen a release; it must never compress it to catch up.
    for previous, current in zip(driver.commands, driver.commands[1:]):
        assert current[0] - previous[0] >= 0.025
    assert not any('left' in name for name in player.get_node_names())


@pytest.mark.parametrize('pose,expected', [
    ('READY', ['READY']), ('PRESS_C', ['READY', 'PRESS_C', 'READY']),
])
def test_pose_test_accepts_unverified_calibration_and_sends_only_selected_pose(
        rig, pose, expected):
    configuration = yaml.safe_load(rig.config.read_text())
    for entry in configuration['poses'].values():
        entry['verified'] = False
    rig.config.write_text(yaml.safe_dump(configuration))
    driver = rig.fake_driver()
    player, _ = rig.player(mode='pose_test', pose=pose)
    rig.spin_until(lambda: player.done)
    rig.spin_for(0.08)
    assert not player.failed
    assert pose_names(driver) == expected


def test_other_runs_readiness_cannot_unlock_player_and_wait_expires(rig, monkeypatch):
    driver = rig.fake_driver(ready_topic='/single_hand_test/another_run/ready')
    player, _ = rig.player()
    rig.spin_for(0.25)
    assert driver.commands == []
    assert not player.done
    # Change only the player's monotonic clock, not ROS timers or this test's clock.
    monkeypatch.setattr(player_module, 'time', SimpleNamespace(
        monotonic=lambda: time.monotonic() + 11))
    player._tick()
    rig.spin_for(0.05)
    assert player.done and player.failed
    assert driver.commands == []


def test_unrelated_publisher_on_current_ready_topic_cannot_impersonate_driver(rig):
    driver = rig.fake_driver(name='unrelated_right_hand_driver')
    player, _ = rig.player()
    rig.spin_for(0.3)
    assert driver.commands == []
    assert not player.done


def test_old_feedback_samples_do_not_unlock_startup(rig):
    driver = rig.fake_driver()
    driver.old_state_stamp = True
    rig.player()
    rig.spin_for(0.3)
    assert driver.commands == []


def test_ready_state_without_command_subscription_does_not_start(rig):
    driver = rig.fake_driver()
    driver.destroy_subscription(driver.command_subscription)
    player, _ = rig.player()
    rig.spin_for(0.3)
    assert not player.done
    assert driver.commands == []
    assert player.command_publisher.get_subscription_count() == 0


@pytest.mark.parametrize('failure', ['stale_state', 'stale_ready', 'false_ready', 'abort'])
def test_fault_stops_without_sending_release_or_any_later_note(rig, failure):
    driver = rig.fake_driver()
    player, _ = rig.player(press_duration=2.0)
    rig.spin_until(lambda: len(driver.commands) == 2)
    assert pose_names(driver)[-1] == 'PRESS_E'
    if failure == 'stale_state':
        driver.emit_state = False
    elif failure == 'stale_ready':
        driver.emit_ready = False
    elif failure == 'false_ready':
        driver.ready = False
    else:
        driver.fault = True
    rig.spin_until(lambda: player.done, timeout=2.0)
    rig.spin_for(0.15)
    assert player.failed
    assert pose_names(driver) == ['READY', 'PRESS_E']


def test_stop_service_releases_once_and_never_resumes(rig):
    driver = rig.fake_driver()
    player, _ = rig.player(press_duration=2.0)
    caller = rig.add(Node('single_hand_stop_caller', context=rig.context))
    client = caller.create_client(Trigger, '/single_hand_piano/stop')
    rig.spin_until(lambda: len(driver.commands) == 2 and client.service_is_ready())
    first = client.call_async(Trigger.Request())
    rig.spin_until(first.done)
    assert first.result().success
    rig.spin_until(lambda: player.done and len(driver.commands) == 3)
    second = client.call_async(Trigger.Request())
    rig.spin_until(second.done)
    rig.spin_for(0.15)
    assert pose_names(driver) == ['READY', 'PRESS_E', 'READY']


def test_stop_after_state_timeout_never_sends_a_release(rig):
    driver = rig.fake_driver()
    player, _ = rig.player(press_duration=2.0)
    caller = rig.add(Node('single_hand_failed_stop_caller', context=rig.context))
    client = caller.create_client(Trigger, '/single_hand_piano/stop')
    rig.spin_until(lambda: len(driver.commands) == 2 and client.service_is_ready())
    driver.emit_state = False
    rig.spin_until(lambda: player.done)
    future = client.call_async(Trigger.Request())
    rig.spin_until(future.done)
    rig.spin_for(0.1)
    assert player.failed
    assert pose_names(driver) == ['READY', 'PRESS_E']


def test_missing_write_confirmation_stops_after_initial_ready(rig):
    driver = rig.fake_driver()
    driver.emit_written = False
    player, _ = rig.player()
    rig.spin_until(lambda: len(driver.commands) == 1)
    rig.spin_until(lambda: player.done, timeout=2.0)
    rig.spin_for(0.1)
    assert player.failed
    assert pose_names(driver) == ['READY']


def test_every_hold_starts_after_write_confirmation_without_queueing(rig):
    driver = rig.fake_driver()
    driver.emit_written = False
    player, _ = rig.player(ready_settle=0.15, press_duration=0.15, release_duration=0.15)
    rig.spin_until(lambda: len(driver.commands) == 1)
    # READY settling, PRESS holding and READY releasing all start after a write ack.
    for command_count in (1, 2, 3):
        rig.spin_for(0.12)
        assert len(driver.commands) == command_count
        assert not player.done
        confirmed_at = time.monotonic()
        driver.written.publish(driver.command_messages[-1])
        rig.spin_for(0.1)
        assert len(driver.commands) == command_count
        rig.spin_until(lambda: len(driver.commands) == command_count + 1)
        assert driver.commands[-1][0] - confirmed_at >= 0.14
    assert pose_names(driver) == ['READY', 'PRESS_E', 'READY', 'PRESS_E']


def test_stop_during_pending_press_waits_then_releases_once(rig):
    driver = rig.fake_driver()
    player, _ = rig.player(ready_settle=0.2, press_duration=2.0)
    caller = rig.add(Node('single_hand_pending_stop_caller', context=rig.context))
    client = caller.create_client(Trigger, '/single_hand_piano/stop')
    rig.spin_until(lambda: len(driver.commands) == 1)
    driver.emit_written = False
    rig.spin_until(lambda: len(driver.commands) == 2 and client.service_is_ready())
    future = client.call_async(Trigger.Request())
    rig.spin_until(future.done)
    assert future.result().success
    rig.spin_for(0.12)
    assert not player.done
    assert pose_names(driver) == ['READY', 'PRESS_E']
    driver.emit_written = True
    driver.written.publish(driver.command_messages[-1])
    rig.spin_until(lambda: player.done)
    rig.spin_for(0.1)
    assert not player.failed
    assert pose_names(driver) == ['READY', 'PRESS_E', 'READY']
