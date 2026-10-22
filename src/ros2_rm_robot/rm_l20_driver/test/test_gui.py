"""Exercise the Qt controls and ROS topic boundary without physical hardware."""

import copy
import os
from pathlib import Path
import time
from types import SimpleNamespace
import uuid

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PyQt5')
rclpy = pytest.importorskip('rclpy')
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PyQt5.QtGui import QMouseEvent  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication, QFileDialog, QMessageBox, QStyle, QStyleOptionSlider,
)
from rclpy.context import Context  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402

from rm_l20_driver.gui import HandGuiNode, HandWindow  # noqa: E402
from rm_l20_driver.gui_core import (  # noqa: E402
    ACTIVE_SLOTS, RESERVED_SLOTS, feedback_target, load_pose_file, save_pose,
)


@pytest.fixture(scope='module')
def application():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


@pytest.fixture
def gui(application, monkeypatch):
    """Use real Qt/ROS objects, a controlled clock, and recording publishers."""
    monkeypatch.setenv('ROS_DOMAIN_ID', '219')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    context = Context()
    rclpy.init(context=context)
    now = [100.0]
    topic = '/l20/startup/run_' + uuid.uuid4().hex
    node = HandGuiNode(
        clock=lambda: now[0], context=context, use_global_arguments=False,
        parameter_overrides=[Parameter('ready_topic', value=topic)])
    commands = {side: [] for side in ('left', 'right')}
    subscribers = {'left': 1, 'right': 1}
    for side, publisher in node.command_publishers.items():
        monkeypatch.setattr(publisher, 'publish', commands[side].append)
        monkeypatch.setattr(publisher, 'get_subscription_count',
                            lambda selected=side: subscribers[selected])
    window = HandWindow(node, start_timer=False)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[-1]))

    def ready():
        node.receive_ready(Bool(data=True))
        for side in ('left', 'right'):
            values = [float(index) for index in range(20)]
            values[11] = 65535.0
            node.receive_state(side, JointState(position=values))
        window.refresh()

    def acknowledge(side):
        node.receive_written(side, commands[side][-1])
        window.refresh()

    yield SimpleNamespace(
        node=node, window=window, panels=window.panels, commands=commands,
        now=now, ready=ready, application=application,
        subscribers=subscribers, warnings=warnings, acknowledge=acknowledge)
    window.close()
    application.processEvents()
    if context.ok():
        context.shutdown()


def test_open_aligns_sliders_and_initial_targets_without_sending(gui):
    gui.window.show()
    gui.ready()
    gui.application.processEvents()
    for side, panel in gui.panels.items():
        values = feedback_target(gui.node.gate.states[side])
        assert panel.targets == values
        assert [slider.value() for slider in panel.sliders] == values
        assert all(panel.sliders[index].isEnabled() for index in ACTIVE_SLOTS)
        assert all(not panel.sliders[index].isEnabled() for index in RESERVED_SLOTS)
        assert all(panel.inputs[index].isReadOnly() for index in RESERVED_SLOTS)
        assert panel.feedback[11].text() == '65535'
        assert panel.send_button.isEnabled()
        assert gui.commands[side] == []


def test_initial_window_is_centered_in_available_desktop(gui):
    available = gui.application.primaryScreen().availableGeometry()
    assert gui.window.x() == available.x() + (available.width() - gui.window.width()) // 2
    assert gui.window.y() == available.y() + (available.height() - gui.window.height()) // 2
    assert gui.window.height() <= available.height()


@pytest.mark.parametrize('side', ['left', 'right'])
def test_edit_and_load_are_local_each_click_sends_only_selected_hand_once(gui, side):
    gui.ready()
    panel = gui.panels[side]
    values = [float(index) + 0.25 for index in range(20)]
    values[0] = 0.12345678901234567
    panel.set_positions(values)
    assert panel.targets == values
    assert panel.send_button.isEnabled()
    assert not any(gui.commands.values())
    panel.inputs[1].setText('12.75')
    panel.sliders[2].setValue(90)
    assert not any(gui.commands.values())
    panel.send_button.click()
    gui.application.processEvents()
    gui.window.refresh()
    assert len(gui.commands[side]) == 1
    assert list(gui.commands[side][0].position) == panel.targets
    assert list(gui.commands[side][0].name)[0] == 'thumb_root1'
    other = 'right' if side == 'left' else 'left'
    assert gui.commands[other] == []
    panel.send_button.click()
    assert len(gui.commands[side]) == 1
    gui.acknowledge(side)
    gui.now[0] += 0.11
    gui.window.refresh()
    panel.send_button.click()
    assert len(gui.commands[side]) == 2


def test_edit_and_new_pose_name_clear_verification(gui):
    panel = gui.panels['right']
    panel.set_positions([12.5] * 20, verified=True)
    assert panel.verified.isChecked()
    panel.inputs[0].setText('13.5')
    assert not panel.verified.isChecked()
    panel.verified.click()
    assert panel.verified.isChecked()
    panel.pose_name.setCurrentText('NEW_POSE')
    assert not panel.verified.isChecked()
    assert not any(gui.commands.values())


@pytest.mark.parametrize('value', ['', 'NaN', 'inf', '-1', '256', 'bad'])
def test_invalid_editor_input_blocks_send_and_save(gui, value):
    gui.ready()
    panel = gui.panels['left']
    panel.set_positions([12.0] * 20, verified=True)
    panel.inputs[0].setText(value)
    assert not panel.send_button.isEnabled()
    assert not panel.save_button.isEnabled()
    assert not panel.verified.isChecked()
    panel.verified.setChecked(True)
    assert not panel.verified.isChecked()
    assert not any(gui.commands.values())


def test_empty_piano_template_loads_without_filling_values_or_sending(gui):
    root = Path(__file__).resolve().parents[2]
    template = root / 'rm_piano_player' / 'config' / 'right_hand_ode_to_joy.yaml'
    panel = gui.panels['right']
    panel.set_positions([10.0] * 20, verified=True)
    panel.load_document(template)
    assert panel.targets == [None] * 20
    assert not panel.verified.isChecked()
    assert panel.pose_name.currentText() == 'READY'
    assert panel.save_path is None
    assert not any(gui.commands.values())


def test_save_load_preserves_other_poses_and_target_precision(gui, tmp_path):
    path = tmp_path / 'right.yaml'
    preserved = [19.0] * 20
    save_pose(path, 'PRESS_C', preserved, verified=True)
    panel = gui.panels['right']
    values = [0.12345678901234567] + [12.5] * 19
    panel.set_positions(values)
    panel.save_to(path)
    result = load_pose_file(path)
    assert result['poses']['READY'] == {'positions': values, 'verified': False}
    assert result['poses']['PRESS_C'] == {'positions': preserved, 'verified': True}
    panel.load_document(path)
    assert panel.targets == values
    panel.pose_name.setCurrentText('PRESS_C')
    panel.load_selected()
    assert panel.targets == preserved and panel.verified.isChecked()
    assert not any(gui.commands.values())


def test_overwrite_requires_confirmation_and_new_file_clears_previous_destination(gui, tmp_path):
    first, second = tmp_path / 'first.yaml', tmp_path / 'second.yaml'
    panel = gui.panels['right']
    panel.set_positions([10.0] * 20)
    panel.save_to(first)
    original = first.read_bytes()
    panel.inputs[0].setText('11')
    with pytest.raises(FileExistsError):
        panel.save_to(first)
    assert first.read_bytes() == original
    panel.save_to(first, overwrite=True)
    save_pose(second, 'READY', [50.0] * 20)
    panel.load_document(second)
    assert panel.save_path is None
    assert panel.path == second and panel.targets == [50.0] * 20
    assert not any(gui.commands.values())


def test_bad_yaml_reports_error_without_replacing_targets(gui, tmp_path, monkeypatch):
    path = tmp_path / 'broken.yaml'
    path.write_text('poses: [not closed', encoding='utf-8')
    panel = gui.panels['right']
    panel.set_positions([30.0] * 20)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    panel.choose_file()
    assert gui.warnings
    assert panel.targets == [30.0] * 20
    assert panel.path is None
    assert not any(gui.commands.values())


@pytest.mark.parametrize('failure', ['false', 'stale_left', 'stale_right', 'heartbeat'])
def test_faults_disable_both_hands_and_fresh_packets_cannot_resume(gui, failure):
    gui.ready()
    for panel in gui.panels.values():
        panel.set_positions([10.0] * 20)
    if failure == 'false':
        gui.node.receive_ready(Bool(data=False))
    elif failure == 'heartbeat':
        for _ in range(13):
            gui.now[0] += 0.2
            for side in ('left', 'right'):
                gui.node.receive_state(side, JointState(position=[1.0] * 20))
    else:
        stale = failure.removeprefix('stale_')
        fresh = 'right' if stale == 'left' else 'left'
        for _ in range(3):
            gui.now[0] += 0.2
            gui.node.receive_state(fresh, JointState(position=[1.0] * 20))
            gui.node.receive_ready(Bool(data=True))
    gui.ready()
    gui.window.refresh()
    assert gui.node.gate.fault
    assert all(not panel.send_button.isEnabled() for panel in gui.panels.values())
    for side in ('left', 'right'):
        with pytest.raises(RuntimeError):
            gui.node.send(side, [10.0] * 20)
    assert not any(gui.commands.values())


def test_missing_subscription_blocks_both_hands_without_queuing(gui):
    gui.ready()
    for panel in gui.panels.values():
        panel.set_positions([10.0] * 20)
    gui.subscribers['right'] = 0
    gui.window.refresh()
    assert all(not panel.send_button.isEnabled() for panel in gui.panels.values())
    gui.subscribers['right'] = 1
    gui.window.refresh()
    assert all(panel.send_button.isEnabled() for panel in gui.panels.values())
    assert not any(gui.commands.values())


def test_click_rechecks_deadline_even_before_next_ui_tick(gui):
    gui.ready()
    panel = gui.panels['left']
    panel.set_positions([20.0] * 20)
    assert panel.send_button.isEnabled()
    gui.now[0] += 0.501
    panel.send_button.click()
    assert gui.warnings and gui.node.gate.fault
    assert not any(gui.commands.values())


def test_window_close_stops_executor_and_never_sends_a_release_pose(gui):
    gui.ready()
    gui.panels['left'].set_positions([10.0] * 20)
    gui.window.timer.start()
    gui.window.close()
    gui.application.processEvents()
    gui.window.shutdown()
    assert gui.window._closed
    assert not gui.window.timer.isActive()
    assert not any(gui.commands.values())


def move_slider(panel, index, value, *, release=True):
    """Exercise the public Qt slider gesture signals, not GUI private handlers."""
    slider = panel.sliders[index]
    slider.setSliderDown(True)
    slider.setSliderPosition(value)
    if release:
        slider.setSliderDown(False)


def test_feedback_tracks_sliders_without_overwriting_loaded_targets(gui):
    gui.ready()
    panel = gui.panels['right']
    panel.set_positions([200.5] * 20, verified=True)
    gui.node.receive_state('right', JointState(position=[40.0] * 20))
    gui.window.refresh()
    assert all(panel.sliders[index].value() == 40 for index in ACTIVE_SLOTS)
    assert panel.targets == [200.5] * 20
    assert panel.verified.isChecked()
    assert not any(gui.commands.values())


@pytest.mark.parametrize('side', ['left', 'right'])
def test_drag_sends_selected_joint_from_current_feedback_not_loaded_pose(gui, side):
    gui.ready()
    panel = gui.panels[side]
    panel.set_positions([240.0] * 20, verified=True)
    move_slider(panel, 2, 80)
    assert not panel.verified.isChecked()
    gui.window.tick()
    expected = feedback_target(gui.node.gate.states[side])
    expected[2] = 80.0
    assert list(gui.commands[side][0].position) == expected
    assert len(gui.commands[side]) == 1
    other = 'right' if side == 'left' else 'left'
    assert gui.commands[other] == []
    assert all(value == 0 for value in list(gui.commands[side][0].position)[11:15])


def test_press_without_moving_and_programmatic_changes_never_send(gui):
    gui.ready()
    panel = gui.panels['left']
    slider = panel.sliders[0]
    slider.setSliderDown(True)
    slider.setSliderDown(False)
    gui.window.tick()
    slider.setValue(99)
    panel.inputs[0].setText('123')
    gui.window.tick()
    assert not any(gui.commands.values())


def test_drag_coalesces_at_ten_hz_and_feedback_cannot_pull_active_slider(gui):
    gui.ready()
    panel = gui.panels['right']
    move_slider(panel, 0, 50, release=False)
    gui.window.tick()
    for value in (60, 70, 80):
        panel.sliders[0].setSliderPosition(value)
    gui.now[0] += 0.11
    gui.ready()
    gui.window.tick()
    assert panel.sliders[0].value() == 80
    assert len(gui.commands['right']) == 1
    gui.acknowledge('right')
    gui.window.tick()
    assert len(gui.commands['right']) == 2
    assert gui.commands['right'][-1].position[0] == 80
    panel.sliders[0].setSliderPosition(90)
    panel.sliders[0].setSliderDown(False)
    gui.acknowledge('right')
    gui.window.tick()
    assert len(gui.commands['right']) == 2
    gui.now[0] += 0.11
    gui.window.tick()
    assert len(gui.commands['right']) == 3
    assert gui.commands['right'][-1].position[0] == 90
    gui.node.receive_state('right', JointState(position=[42.0] * 20))
    gui.acknowledge('right')
    gui.window.tick()
    assert panel.sliders[0].value() == 42
    assert panel.targets[0] == 90
    assert len(gui.commands['right']) == 3
    assert gui.commands['left'] == []


def test_keyboard_slider_action_controls_but_set_value_does_not(gui):
    gui.ready()
    panel = gui.panels['left']
    panel.sliders[0].triggerAction(panel.sliders[0].SliderSingleStepAdd)
    gui.window.tick()
    assert len(gui.commands['left']) == 1
    assert gui.commands['left'][0].position[0] == 1


def test_mouse_drag_preserves_and_sends_final_position_once(gui):
    """Use Qt mouse press/move/release ordering with the left button held."""
    gui.window.show()
    gui.application.processEvents()
    gui.ready()
    panel = gui.panels['left']
    slider = panel.sliders[0]
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    handle = slider.style().subControlRect(
        QStyle.CC_Slider, option, QStyle.SC_SliderHandle, slider)
    QTest.mousePress(slider, Qt.LeftButton, pos=handle.center())
    assert slider.isSliderDown()
    for fraction in (0.35, 0.7):
        position = QPoint(round(slider.width() * fraction), handle.center().y())
        event = QMouseEvent(
            QEvent.MouseMove, QPointF(position), QPointF(slider.mapToGlobal(position)),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        gui.application.sendEvent(slider, event)
        gui.window.tick()
    final_position = slider.sliderPosition()
    assert final_position > gui.commands['left'][0].position[0]
    QTest.mouseRelease(slider, Qt.LeftButton, pos=position)
    assert not slider.isSliderDown()
    assert len(gui.commands['left']) == 1
    gui.acknowledge('left')
    gui.now[0] += 0.11
    gui.window.tick()
    assert len(gui.commands['left']) == 2
    assert gui.commands['left'][-1].position[0] == final_position
    gui.acknowledge('left')
    gui.window.tick()
    assert len(gui.commands['left']) == 2
    assert not gui.commands['right']


@pytest.mark.parametrize('mismatch', ['old_session', 'target', 'side'])
def test_unrelated_write_confirmation_cannot_release_pending_target(gui, mismatch):
    gui.ready()
    panel = gui.panels['right']
    move_slider(panel, 0, 50, release=False)
    gui.window.tick()
    panel.sliders[0].setSliderPosition(70)
    message = copy.deepcopy(gui.commands['right'][0])
    side = 'right'
    if mismatch == 'old_session':
        message.header.frame_id = 'old_gui/1'
    elif mismatch == 'target':
        message.position[0] = 60.0
    else:
        side = 'left'
    gui.node.receive_written(side, message)
    gui.now[0] += 0.11
    gui.window.tick()
    assert gui.node.inflight['right'] is not None
    assert len(gui.commands['right']) == 1
    gui.acknowledge('right')
    gui.window.tick()
    assert len(gui.commands['right']) == 2


def test_missing_write_confirmation_latches_fault_and_late_ack_cannot_resume(gui):
    gui.ready()
    move_slider(gui.panels['right'], 0, 50, release=False)
    gui.window.tick()
    gui.panels['right'].sliders[0].setSliderPosition(90)
    for _ in range(6):
        gui.now[0] += 0.2
        gui.ready()
    assert '写入确认超时' in gui.node.gate.fault
    gui.acknowledge('right')
    gui.window.tick()
    assert len(gui.commands['right']) == 1
    assert all(value is None for value in gui.node.pending.values())
    assert all(not slider.isEnabled()
               for panel in gui.panels.values() for slider in panel.sliders)


@pytest.mark.parametrize('cancel', ['tab', 'load', 'edit', 'fault', 'subscriber', 'close'])
def test_cancel_drops_unsent_gesture_and_does_not_replay_after_recovery(gui, cancel):
    gui.ready()
    panel = gui.panels['left']
    move_slider(panel, 0, 50)
    assert gui.node.pending['left'] is not None
    if cancel == 'tab':
        gui.window.tabs.setCurrentIndex(1)
    elif cancel == 'load':
        panel.set_positions([100.0] * 20)
    elif cancel == 'edit':
        panel.inputs[0].setText('100')
    elif cancel == 'fault':
        gui.node.receive_ready(Bool(data=False))
        gui.window.refresh()
    elif cancel == 'subscriber':
        gui.subscribers['right'] = 0
        gui.window.refresh()
        gui.subscribers['right'] = 1
    else:
        gui.window.close()
    if cancel != 'close':
        gui.ready()
        gui.window.tick()
    assert gui.node.pending['left'] is None
    assert not any(gui.commands.values())


def test_invalid_active_feedback_disables_sliders_without_clipping(gui):
    gui.ready()
    values = [20.0] * 20
    values[0] = 256.0
    gui.node.receive_state('right', JointState(position=values))
    gui.window.refresh()
    assert gui.node.gate.fault
    assert gui.panels['right'].feedback[0].text() == '256'
    assert all(not slider.isEnabled()
               for panel in gui.panels.values() for slider in panel.sliders)
    assert not any(gui.commands.values())


def test_ros_fake_driver_old_run_readiness_does_not_unlock_gui(application, monkeypatch):
    """Exercise actual DDS delivery, private readiness, and left/right routing."""
    monkeypatch.setenv('ROS_DOMAIN_ID', '219')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    context = Context()
    rclpy.init(context=context)
    topic = '/l20/startup/run_' + uuid.uuid4().hex
    node = HandGuiNode(
        context=context, use_global_arguments=False,
        parameter_overrides=[Parameter('ready_topic', value=topic)])
    observer = Node('gui_fake_driver', context=context, use_global_arguments=False)
    window = HandWindow(node, start_timer=False)
    window.executor.add_node(observer)
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)
    old_ready = observer.create_publisher(Bool, '/l20/startup/old_run', qos)
    current_ready = observer.create_publisher(Bool, topic, qos)
    states = {side: observer.create_publisher(JointState, f'/cb_{side}_hand_state', 10)
              for side in ('left', 'right')}
    commands = {side: [] for side in ('left', 'right')}
    acknowledgements = {
        side: observer.create_publisher(JointState, f'/{side}_l20_driver/command_written', 10)
        for side in ('left', 'right')}

    def receive_command(side, message):
        commands[side].append(message)
        acknowledgements[side].publish(message)

    subscriptions = [observer.create_subscription(
        JointState, f'/cb_{side}_hand_control_cmd',
        lambda message, selected=side: receive_command(selected, message), 10)
        for side in ('left', 'right')]

    def pump(duration, ready_publisher):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            ready_publisher.publish(Bool(data=True))
            for publisher in states.values():
                publisher.publish(JointState(position=[100.0] * 20))
            window.tick()
            application.processEvents()
            time.sleep(0.01)

    try:
        assert subscriptions
        window.panels['right'].set_positions([12.5] * 20)
        pump(0.7, old_ready)
        assert node.gate.states
        assert not window.panels['right'].send_button.isEnabled()
        assert not any(commands.values())
        pump(0.2, current_ready)
        assert window.panels['right'].send_button.isEnabled(), node.blocked_reason()
        window.panels['right'].send_button.click()
        pump(0.15, current_ready)
        assert len(commands['right']) == 1 and commands['left'] == []
        assert list(commands['right'][0].position) == [12.5] * 20
        assert node.inflight['right'] is None
        current_ready.publish(Bool(data=False))
        deadline = time.monotonic() + 0.3
        while not node.gate.fault and time.monotonic() < deadline:
            window.tick()
            application.processEvents()
        assert node.gate.fault
        assert not window.panels['right'].send_button.isEnabled()
    finally:
        window.executor.remove_node(observer)
        window.close()
        observer.destroy_node()
        if context.ok():
            context.shutdown()
