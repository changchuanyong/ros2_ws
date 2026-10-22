"""Feedback-aligned L20 slider control through ROS, without serial ownership."""

import math
import os
from pathlib import Path
import signal
import sys
import time
import uuid

try:
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout,
        QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
        QScrollArea, QSlider, QTabWidget, QVBoxLayout, QWidget,
    )
except ImportError as error:
    raise SystemExit(
        'L20 GUI needs python3-pyqt5; install the documented GUI dependencies.') from error

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool

try:
    import yaml

    from rm_l20_driver.gui_core import (
        ACTIVE_SLOTS, JOINT_LABELS, POSE_NAMES, RESERVED_SLOTS, SIDES,
        ReadinessGate, feedback_target, load_pose_file, read_pose, save_pose,
        validate_target,
    )
except ModuleNotFoundError as error:
    if error.name == 'yaml':
        raise SystemExit(
            'L20 GUI needs python3-yaml; install the documented GUI dependencies.') from error
    raise


SIDE_LABELS = {'left': '左手', 'right': '右手'}
JOINT_NAMES = [f'{finger}_{group}' for group in ('root1', 'yaw', 'roll', 'tip')
               for finger in ('thumb', 'index', 'middle', 'ring', 'little')]


class HandGuiNode(Node):
    """Own ROS publishers and enforce a fresh, run-specific command gate."""

    def __init__(self, *, clock=time.monotonic, **kwargs):
        super().__init__('l20_hand_gui', **kwargs)
        self.clock = clock
        self.gate = ReadinessGate(clock=clock)
        self.pending = dict.fromkeys(SIDES)
        self.inflight = dict.fromkeys(SIDES)
        self.last_send = dict.fromkeys(SIDES, float('-inf'))
        self._session = uuid.uuid4().hex
        self._sequence = 0
        self._stopped = False
        try:
            self.declare_parameter('ready_topic', '')
            topic = self.get_parameter('ready_topic').value
            if (not isinstance(topic, str) or not topic.startswith('/') or
                    topic == '/l20/hands_ready'):
                raise ValueError('ready_topic must be this launch run\'s private absolute topic')
            self.command_publishers = {
                side: self.create_publisher(JointState, f'/cb_{side}_hand_control_cmd', 10)
                for side in SIDES
            }
            qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.ready_subscription = self.create_subscription(
                Bool, topic, self.receive_ready, qos)
            self.state_subscriptions = [
                self.create_subscription(
                    JointState, f'/cb_{side}_hand_state',
                    lambda message, selected=side: self.receive_state(selected, message), 10)
                for side in SIDES
            ]
            self.written_subscriptions = [
                self.create_subscription(
                    JointState, f'/{side}_l20_driver/command_written',
                    lambda message, selected=side: self.receive_written(selected, message), 10)
                for side in SIDES
            ]
        except BaseException:
            super().destroy_node()
            raise

    def receive_ready(self, message):
        self.gate.update_ready(message.data)

    def receive_state(self, side, message):
        self.gate.update_state(side, list(message.position))

    def blocked_reason(self):
        if self._stopped:
            return '界面已关闭'
        for side, item in self.inflight.items():
            if item is not None and self.clock() - item[1] > 1.0 and not self.gate.fault:
                self.gate.fault = f'{SIDE_LABELS[side]}位置写入确认超时；请重新启动'
        reason = self.gate.reason({
            side: publisher.get_subscription_count()
            for side, publisher in self.command_publishers.items()
        })
        if reason:
            self.cancel_pending()
        return reason

    def receive_written(self, side, message):
        """Match this session's write acknowledgement, not physical arrival."""
        if self.blocked_reason():
            return
        item = self.inflight[side]
        if item is not None:
            expected = item[0]
            if (message.header == expected.header and message.name == expected.name and
                    list(message.position) == list(expected.position)):
                self.inflight[side] = None

    def busy(self, side):
        return self.pending[side] is not None or self.inflight[side] is not None

    def cancel_pending(self, side=None):
        """Drop unsent targets; a command already on the wire cannot be recalled."""
        for selected in SIDES if side is None else (side,):
            self.pending[selected] = None

    def request_live(self, side, positions):
        """Coalesce a user gesture into one latest target without a command queue."""
        values = validate_target(positions)
        reason = self.blocked_reason()
        if reason:
            raise RuntimeError(reason)
        item = self.inflight[side]
        self.pending[side] = (None if item is not None and
                              list(item[0].position) == values else values)

    def flush_pending(self):
        """Send at most 10 Hz per hand, with at most one unacknowledged write."""
        if self.blocked_reason():
            return
        for side in SIDES:
            if (self.pending[side] is not None and self.inflight[side] is None and
                    self.clock() - self.last_send[side] >= 0.1):
                values = self.pending[side]
                self.pending[side] = None
                self._publish(side, values)

    def send(self, side, positions):
        """Manually publish once, sharing the same gate and in-flight limit."""
        if side not in SIDES:
            raise ValueError('unknown hand')
        values = validate_target(positions)
        reason = self.blocked_reason()
        if reason:
            raise RuntimeError(reason)
        if self.busy(side) or self.clock() - self.last_send[side] < 0.1:
            raise RuntimeError('等待上一条位置命令确认及发送间隔')
        self._publish(side, values)

    def _publish(self, side, values):
        reason = self.blocked_reason()
        if reason:
            raise RuntimeError(reason)
        message = JointState()
        message.header.stamp = self.get_clock().now().to_msg()
        self._sequence += 1
        message.header.frame_id = f'l20_gui/{self._session}/{self._sequence}'
        message.name = list(JOINT_NAMES)
        message.position = values
        self.inflight[side] = (message, self.clock())
        self.last_send[side] = self.clock()
        try:
            self.command_publishers[side].publish(message)
        except Exception as error:
            self.gate.fault = f'位置命令发布失败；请重新启动：{error}'
            self.cancel_pending()
            raise RuntimeError(self.gate.fault) from error

    def stop_sending(self):
        self._stopped = True
        self.cancel_pending()


class HandPanel(QWidget):
    """Keep editable command values separate from read-only raw feedback."""

    def __init__(self, side, node, parent=None):
        super().__init__(parent)
        self.side = side
        self.node = node
        self.targets = [None] * 20
        self.document = {'poses': {}}
        self.path = None
        self.save_path = None
        self._loading = False
        self._initialized = False
        self._active_index = None
        self._tracking_index = None
        self._last_requested = None
        self.inputs = []
        self.sliders = []
        self.feedback = []
        layout = QVBoxLayout(self)
        self.state_label = QLabel('等待本次驱动就绪与双手反馈')
        layout.addWidget(self.state_label)
        note = QLabel('滑块显示实际位置，拖动即控制本手；拖动时显示目标。'
                      '打开、加载和编辑数值不发送。只控制位置，不设置速度或力矩。')
        note.setWordWrap(True)
        layout.addWidget(note)

        fields = QWidget()
        grid = QGridLayout(fields)
        for column, text in enumerate(('关节 / 协议槽位', '实际位置 / 拖动控制', '目标值 0–255', '实际反馈')):
            grid.addWidget(QLabel(text), 0, column)
        for index, label in enumerate(JOINT_LABELS):
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 255)
            slider.setSingleStep(1)
            slider.setToolTip('拖动、点击或键盘调节会发送位置命令；松开后恢复实际位置显示。')
            slider.setEnabled(False)
            editor = QLineEdit()
            editor.setPlaceholderText('未填写')
            editor.setMaximumWidth(120)
            editor.setReadOnly(index in RESERVED_SLOTS)
            feedback = QLabel('—')
            feedback.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(QLabel(f'{index:02d}  {label}'), index + 1, 0)
            grid.addWidget(slider, index + 1, 1)
            grid.addWidget(editor, index + 1, 2)
            grid.addWidget(feedback, index + 1, 3)
            slider.sliderPressed.connect(lambda slot=index: self._begin_drag(slot))
            slider.sliderMoved.connect(lambda value, slot=index: self._drag_to(slot, value))
            slider.sliderReleased.connect(
                lambda slot=index: self._end_drag(slot))
            slider.actionTriggered.connect(
                lambda action, slot=index: self._slider_action(slot, action))
            editor.textChanged.connect(lambda text, slot=index: self._text_changed(slot, text))
            self.sliders.append(slider)
            self.inputs.append(editor)
            self.feedback.append(feedback)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(fields)
        layout.addWidget(scroll, 1)

        row = QHBoxLayout()
        self.pose_name = QComboBox()
        self.pose_name.setEditable(True)
        self.pose_name.addItems(POSE_NAMES)
        row.addWidget(QLabel('姿态名称'))
        row.addWidget(self.pose_name, 1)
        load_button = QPushButton('打开姿态文件')
        load_button.clicked.connect(self.choose_file)
        row.addWidget(load_button)
        select_button = QPushButton('载入所选姿态')
        select_button.clicked.connect(self.load_selected)
        row.addWidget(select_button)
        layout.addLayout(row)
        self.file_label = QLabel('尚未选择文件；左右手文件分别保存')
        self.file_label.setWordWrap(True)
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.file_label)

        actions = QHBoxLayout()
        self.verified = QCheckBox('已实机验证（人工确认）')
        self.verified.setToolTip('只在人工完成该姿态的实机验证后勾选；修改目标会取消此标记。')
        self.verified.toggled.connect(self._verification_changed)
        self.pose_name.currentTextChanged.connect(lambda _: self.verified.setChecked(False))
        actions.addWidget(self.verified)
        self.save_button = QPushButton('保存 / 另存姿态')
        self.save_button.clicked.connect(self.choose_save_file)
        actions.addWidget(self.save_button)
        self.send_button = QPushButton(f'发送{SIDE_LABELS[side]}一次')
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_once)
        actions.addWidget(self.send_button)
        layout.addLayout(actions)
        self.message_label = QLabel('等待有效位置反馈自动对齐滑块；对齐不会发送动作。')
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

    def _text_changed(self, index, text):
        try:
            value = float(text)
            if not math.isfinite(value) or not 0 <= value <= 255:
                value = None
        except ValueError:
            value = None
        changed = self.targets[index] != value
        self.targets[index] = value
        if changed and not self._loading:
            self._initialized = True
            self.cancel_interaction()
            self.verified.setChecked(False)
        self.refresh(self.node.blocked_reason())

    def _begin_drag(self, index):
        if index in RESERVED_SLOTS or self.node.blocked_reason() or self.node.busy(self.side):
            return False
        # Never include an unsent loaded pose in a single-joint gesture.
        values = feedback_target(self.node.gate.states[self.side])
        self._replace_targets(values)
        self._active_index = self._tracking_index = index
        self._last_requested = None
        return True

    def _drag_to(self, index, value):
        if self._active_index != index:
            return
        reason = self.node.blocked_reason()
        if reason:
            self.cancel_interaction()
            self.message_label.setText(reason)
            return
        values = list(self.targets)
        values[index] = float(value)
        if self._last_requested is None and values == self.targets:
            return
        self._replace_targets(values)
        if values != self._last_requested:
            try:
                self.node.request_live(self.side, values)
            except (RuntimeError, ValueError) as error:
                self.cancel_interaction()
                self.message_label.setText(f'实时控制已停止：{error}')
                return
            self._last_requested = values
            self.message_label.setText('拖动控制：仅发送最新目标，等待串口写入确认；不代表已到位。')

    def _end_drag(self, index):
        if self._active_index == index:
            self._drag_to(index, self.sliders[index].sliderPosition())
            self._active_index = None

    def _slider_action(self, index, action):
        slider = self.sliders[index]
        if slider.isSliderDown() or action == QSlider.SliderNoAction:
            return
        value = slider.sliderPosition()
        if self._begin_drag(index):
            self._drag_to(index, value)
            self._active_index = None

    def cancel_interaction(self):
        self.node.cancel_pending(self.side)
        self._active_index = self._tracking_index = None
        self._last_requested = None

    def _verification_changed(self, checked):
        if checked and not self._loading:
            try:
                validate_target(self.targets)
            except ValueError:
                self.verified.setChecked(False)
                self.message_label.setText('目标未完整或数值无效，不能标记为已实机验证。')

    def set_positions(self, positions, verified=False):
        """Load exact numeric targets without reading sliders back or publishing."""
        self.cancel_interaction()
        self._replace_targets(positions, verified)
        self.refresh(self.node.blocked_reason())

    def _replace_targets(self, positions, verified=False):
        values = validate_target(positions) if positions else [None] * 20
        self._initialized = True
        self.targets = list(values)
        self._loading = True
        try:
            for editor, value in zip(self.inputs, values):
                editor.blockSignals(True)
                editor.setText('' if value is None else format(value, '.17g'))
                editor.blockSignals(False)
            self.verified.setChecked(bool(verified) and bool(positions))
        finally:
            self._loading = False

    def load_document(self, path):
        document = load_pose_file(path)
        names = list(document['poses'])
        selected = 'READY' if 'READY' in names else (names[0] if names else 'READY')
        values, verified = read_pose(document, selected) if names else ([], False)
        self.document, self.path = document, Path(path)
        self.save_path = None
        self.pose_name.clear()
        self.pose_name.addItems(list(dict.fromkeys((*POSE_NAMES, *names))))
        self.pose_name.setCurrentText(selected)
        self.set_positions(values, verified)
        self.file_label.setText(f'{SIDE_LABELS[self.side]}文件：{self.path}')
        self.message_label.setText('姿态已载入编辑区，尚未发送。')

    def choose_file(self):
        self.cancel_interaction()
        path, _ = QFileDialog.getOpenFileName(
            self, f'打开{SIDE_LABELS[self.side]}姿态文件', str(self.path or Path.home()),
            'YAML (*.yaml *.yml)')
        if path:
            try:
                self.load_document(path)
            except (OSError, ValueError, yaml.YAMLError) as error:
                self.show_error(error)

    def load_selected(self):
        try:
            values, verified = read_pose(self.document, self.pose_name.currentText().strip())
            self.set_positions(values, verified)
            self.message_label.setText('姿态已载入编辑区，尚未发送。')
        except (KeyError, ValueError) as error:
            self.show_error(error)

    def save_to(self, path, *, overwrite=False):
        """Save command targets only; the selected feedback never enters the file."""
        document = save_pose(
            path, self.pose_name.currentText().strip(), self.targets,
            verified=self.verified.isChecked(), overwrite=overwrite)
        self.document = document
        self.path = self.save_path = Path(path)
        self.file_label.setText(f'{SIDE_LABELS[self.side]}文件：{self.path}')
        self.message_label.setText('目标姿态已保存；没有发送命令。')

    def choose_save_file(self):
        self.cancel_interaction()
        try:
            validate_target(self.targets)
        except ValueError as error:
            self.show_error(error)
            return
        # Loading a package template must not silently make it the save destination.
        initial = self.save_path or Path.home() / f'{self.side}_hand_poses.yaml'
        path, _ = QFileDialog.getSaveFileName(
            self, f'保存{SIDE_LABELS[self.side]}目标姿态', str(initial),
            'YAML (*.yaml *.yml)', options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        try:
            try:
                self.save_to(path)
            except FileExistsError:
                answer = QMessageBox.question(
                    self, '确认覆盖同名姿态',
                    f'{path}\n已存在姿态 {self.pose_name.currentText()}。\n'
                    '是否覆盖此姿态？文件内其他姿态将保留。',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer == QMessageBox.Yes:
                    self.save_to(path, overwrite=True)
        except (OSError, ValueError, yaml.YAMLError) as error:
            self.show_error(error)

    def send_once(self):
        try:
            self.cancel_interaction()
            self.node.send(self.side, self.targets)
        except (RuntimeError, ValueError) as error:
            self.show_error(error)
        else:
            stamp = time.strftime('%H:%M:%S')
            self.message_label.setText(
                f'{stamp} 已发布一次{SIDE_LABELS[self.side]}位置命令；不代表动作或按键完成。')
        self.refresh(self.node.blocked_reason())

    def show_error(self, error):
        self.message_label.setText(f'操作失败：{error}')
        QMessageBox.warning(self, 'L20 调试', str(error))

    def refresh(self, reason):
        if reason:
            self.cancel_interaction()
        values = self.node.gate.states.get(self.side)
        if values is not None:
            for label, value in zip(self.feedback, values):
                label.setText(format(value, '.17g'))
        if not reason and values is not None:
            current = feedback_target(values)
            if not self._initialized:
                self._replace_targets(current)
                self.message_label.setText('已按当前反馈对齐；拖动滑块即控制，不自动发送初始姿态。')
            if self._active_index is None and not self.node.busy(self.side):
                self._tracking_index = None
            for index, slider in enumerate(self.sliders):
                if index != self._tracking_index:
                    slider.blockSignals(True)
                    slider.setValue(round(current[index]))
                    slider.blockSignals(False)
        for index, slider in enumerate(self.sliders):
            slider.setEnabled(not reason and index in ACTIVE_SLOTS and
                              (not self.node.busy(self.side) or self._active_index == index))
        try:
            validate_target(self.targets)
            valid = True
        except ValueError:
            valid = False
        self.send_button.setEnabled(not reason and valid and not self.node.busy(self.side) and
                                    self._active_index is None and
                                    self.node.clock() - self.node.last_send[self.side] >= 0.1)
        self.save_button.setEnabled(valid)
        timestamp = self.node.gate.state_times.get(self.side)
        age = '尚未收到' if timestamp is None else f'{max(0, self.node.clock() - timestamp):.2f} 秒前'
        state = reason or ('等待本手写入确认' if self.node.busy(self.side) else '双手已就绪，拖动即控制')
        self.state_label.setText(f'{state}  |  本手反馈：{age}')


class HandWindow(QMainWindow):
    """Process ROS events in bounded Qt ticks and own deterministic cleanup."""

    def __init__(self, node, *, start_timer=True):
        super().__init__()
        self.node = node
        self._closed = False
        self.executor = SingleThreadedExecutor(context=node.context)
        self.executor.add_node(node)
        self.setWindowTitle('L20 双手 RS485 调试 — 实时位置控制')
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1000, max(400, available.width() - 40)),
                    min(850, max(300, available.height() - 80)))
        self.move(available.x() + (available.width() - self.width()) // 2,
                  available.y() + (available.height() - self.height()) // 2)
        self.tabs = QTabWidget()
        self.panels = {side: HandPanel(side, node, self) for side in SIDES}
        for side, panel in self.panels.items():
            self.tabs.addTab(panel, SIDE_LABELS[side])
        self.tabs.currentChanged.connect(self.cancel_interactions)
        self.setCentralWidget(self.tabs)
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.tick)
        if start_timer:
            self.timer.start()
        self.refresh()

    def tick(self):
        if not rclpy.ok(context=self.node.context):
            self.close()
            return
        # Check deadlines before callbacks can replace old samples with new ones.
        self.node.blocked_reason()
        try:
            for _ in range(8):
                self.executor.spin_once(timeout_sec=0)
            self.node.flush_pending()
        except ExternalShutdownException:
            self.close()
            return
        except Exception as error:
            if not rclpy.ok(context=self.node.context):
                self.close()
                return
            self.node.gate.fault = f'ROS 通信异常，需重新启动：{error}'
        self.refresh()

    def cancel_interactions(self, *_):
        for panel in self.panels.values():
            panel.cancel_interaction()
        self.refresh()

    def refresh(self):
        reason = self.node.blocked_reason()
        for panel in self.panels.values():
            panel.refresh(reason)

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self.node.stop_sending()
        self.executor.shutdown(timeout_sec=0)
        self.node.destroy_node()

    def closeEvent(self, event):
        self.shutdown()
        event.accept()


def main(args=None):
    """Start a desktop GUI without changing hardware settings or sending a pose."""
    if (not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY') and
            os.environ.get('QT_QPA_PLATFORM') not in ('offscreen', 'minimal')):
        print('L20 GUI needs a desktop display. Use use_gui:=false over headless SSH.',
              file=sys.stderr)
        return 1
    application = QApplication(sys.argv[:1])
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = window = None
    previous_handlers = {}
    try:
        node = HandGuiNode()
        window = HandWindow(node)
        application.aboutToQuit.connect(window.shutdown)
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda *_: application.quit())
        window.show()
        return application.exec_()
    except (KeyboardInterrupt, ExternalShutdownException):
        return 0
    except Exception as error:
        print(f'L20 GUI failed: {error}', file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        if window is not None:
            window.shutdown()
        elif node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
