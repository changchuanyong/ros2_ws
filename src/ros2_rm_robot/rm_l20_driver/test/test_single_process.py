"""Run only the right driver with a virtual hand and isolated ROS readiness."""

import signal
import subprocess
import sys
import time

import pytest

rclpy = pytest.importorskip('rclpy')
from rclpy.context import Context  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402

from rm_l20_driver.discovery import open_hand  # noqa: E402
from test_uid_transport import RIGHT, virtual_hand  # noqa: E402


pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux PTY test')


def test_right_only_process_ready_state_and_clean_shutdown(tmp_path, monkeypatch):
    monkeypatch.setenv('ROS_DOMAIN_ID', '219')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    context = Context()
    rclpy.init(context=context)
    observer = Node('single_process_observer', context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(observer)
    ready, states = [], []
    observer.create_subscription(Bool, '/l20/single/test_process/ready',
                                 lambda msg: ready.append(msg.data), 10)
    observer.create_subscription(JointState, '/cb_right_hand_state', states.append, 10)
    process = None
    log = tmp_path / 'single-process.log'
    try:
        with virtual_hand(RIGHT, state_feedback=True) as (port, requests), log.open('w') as output:
            process = subprocess.Popen([
                sys.executable, '-m', 'rm_l20_driver.node', '--ros-args',
                '-p', 'hand_type:=right', '-p', f'expected_uid:={RIGHT}',
                '-p', f'modbus:={port}',
                '-r', '~/ready:=/l20/single/test_process/ready',
            ], stdout=output, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and process.poll() is None:
                    executor.spin_once(timeout_sec=0.1)
                    if ready.count(True) >= 3 and len(states) >= 2:
                        break
                assert ready.count(True) >= 3 and len(states) >= 2, log.read_text()
                assert observer.count_subscribers('/cb_right_hand_control_cmd') == 1
                assert observer.count_subscribers('/cb_left_hand_control_cmd') == 0
                assert observer.count_publishers('/cb_left_hand_state') == 0
                assert requests  # The helper rejects every write request.
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    pytest.fail('single process did not stop after SIGINT')
            assert process.returncode == 0 and 'Traceback' not in log.read_text(), log.read_text()
            with open_hand(port):
                pass
    finally:
        executor.shutdown()
        observer.destroy_node()
        context.shutdown()
