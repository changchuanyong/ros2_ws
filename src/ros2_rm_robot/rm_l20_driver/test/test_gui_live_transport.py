"""Exercise GUI dragging through ROS and real Modbus transport on PTYs only."""

from contextlib import contextmanager
import os
import select
import struct
import sys
import threading
import time
from types import SimpleNamespace
import uuid

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PyQt5')
rclpy = pytest.importorskip('rclpy')
from PyQt5.QtWidgets import QApplication  # noqa: E402
from rclpy.context import Context  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402

from rm_l20_driver.discovery import open_hand  # noqa: E402
from rm_l20_driver.dual_node import DualHandDriver  # noqa: E402
from rm_l20_driver.gui import HandGuiNode, HandWindow  # noqa: E402
from test_uid_transport import LEFT, RIGHT, frame  # noqa: E402


pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux PTY test')


@contextmanager
def moving_virtual_hand(uid):
    """Acknowledge position writes and expose their effective positions as feedback."""
    master, slave = os.openpty()
    port = os.ttyname(slave)
    assert port.startswith('/dev/pts/'), 'never access physical USB serial devices'
    stop = threading.Event()
    errors, writes = [], []
    positions = list(range(30))
    reserved = (1, 2, 3, 4, *range(15, 25))
    for index in reserved:
        positions[index] = 65535
    uid_words = struct.unpack('<11H', uid.encode('ascii').ljust(22, b'\x00'))

    def worker():
        buffer = bytearray()
        try:
            while not stop.is_set():
                readable, _, _ = select.select([master], [], [], 0.05)
                if not readable:
                    continue
                buffer.extend(os.read(master, 256))
                while len(buffer) >= 8:
                    function = buffer[1]
                    assert function in (4, 16), 'unexpected operation on the fake hand'
                    size = 8 if function == 4 else 9 + buffer[6]
                    if len(buffer) < size:
                        break
                    request = bytes(buffer[:size])
                    del buffer[:size]
                    assert request == frame(request[:-2])
                    slave_id, _, address, count = struct.unpack('>BBHH', request[:6])
                    assert slave_id == 1
                    if function == 4:
                        if address == 212 and count == 11:
                            values = uid_words
                        else:
                            assert address in (0, 30) and count == 30
                            values = positions[:] if address == 0 else [0] * 30
                        reply = frame(bytes([1, 4, count * 2]) +
                                      struct.pack(f'>{count}H', *values))
                    else:
                        assert address == 0 and count == 30 and request[6] == 60
                        values = list(struct.unpack('>30H', request[7:-2]))
                        writes.append(values)
                        positions[:] = values
                        for index in reserved:
                            positions[index] = 65535
                        reply = frame(request[:6])
                    os.write(master, reply)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(port=port, writes=writes)
    finally:
        stop.set()
        thread.join(timeout=1)
        os.close(slave)
        os.close(master)
        assert not thread.is_alive(), 'virtual hand did not stop'
        if errors:
            raise AssertionError('virtual Modbus hand failed') from errors[0]


def test_drag_round_trip_uses_feedback_baseline_and_only_writes_selected_hand(monkeypatch):
    """Startup is read-only; one right-hand drag reaches the simulated fingers."""
    monkeypatch.setenv('ROS_DOMAIN_ID', '224')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    context = Context()
    rclpy.init(context=context)
    topic = '/l20/startup/run_' + uuid.uuid4().hex
    manager = window = node = None
    with moving_virtual_hand(LEFT) as left, moving_virtual_hand(RIGHT) as right:
        try:
            params = {'left_hand_uid': LEFT, 'right_hand_uid': RIGHT,
                      'left_hand_port': left.port, 'right_hand_port': right.port}
            manager = DualHandDriver(
                context=context, use_global_arguments=False,
                cli_args=['--ros-args', '-r', f'~/hands_ready:={topic}'],
                parameter_overrides=[Parameter(key, value=value) for key, value in params.items()])
            node = HandGuiNode(
                context=context, use_global_arguments=False,
                parameter_overrides=[Parameter('ready_topic', value=topic)])
            window = HandWindow(node, start_timer=False)
            manager.initialize()
            for driver_node in (manager, *manager.hands):
                window.executor.add_node(driver_node)
            window.show()

            def pump_until(condition, timeout=3.0):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    window.tick()
                    app.processEvents()
                    assert not node.gate.fault, node.gate.fault
                    assert not manager.faulted
                    if condition():
                        return
                    time.sleep(0.005)
                pytest.fail('GUI/driver round trip timed out: ' + node.blocked_reason())

            panel = window.panels['right']
            pump_until(lambda: not node.blocked_reason())
            window.tabs.setCurrentWidget(panel)
            assert left.writes == right.writes == []
            assert panel.sliders[0].value() == 10
            assert panel.feedback[11].text() == '65535'
            assert all(not panel.sliders[index].isEnabled() for index in range(11, 15))

            # A loaded but unsent pose must not become the other joints' drag baseline.
            panel.set_positions([200.0] * 20)
            app.processEvents()
            assert left.writes == right.writes == []
            slider = panel.sliders[0]
            slider.setSliderDown(True)
            slider.setSliderPosition(180)
            slider.setSliderDown(False)
            pump_until(lambda: bool(right.writes) and node.gate.states['right'][0] == 180)
            pump_until(lambda: not node.busy('right') and panel.sliders[0].value() == 180)
            assert left.writes == []
            assert len(right.writes) == 1
            expected = [0] * 5 + list(range(5, 10)) + [180, 11, 12, 13, 14] + \
                [0] * 10 + list(range(25, 30))
            assert right.writes[-1] == expected

            count = len(right.writes)
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:
                window.tick()
                app.processEvents()
                time.sleep(0.005)
            assert len(right.writes) == count, 'feedback updates must never publish commands'
        finally:
            if window is not None:
                if manager is not None:
                    for driver_node in (manager, *manager.hands):
                        window.executor.remove_node(driver_node)
                window.close()
                app.processEvents()
            elif node is not None:
                node.destroy_node()
            if manager is not None:
                manager.destroy_node()
            if context.ok():
                context.shutdown()
        for port in (left.port, right.port):
            with open_hand(port):
                pass
