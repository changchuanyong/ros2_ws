"""Run the dual process with two PTYs and observe actual ROS readiness and cleanup."""

from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

rclpy = pytest.importorskip('rclpy')
from rclpy.context import Context  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402

from rm_l20_driver.discovery import open_hand  # noqa: E402
from rm_l20_driver.dual_node import ready_qos  # noqa: E402
from test_uid_transport import LEFT, RIGHT, virtual_hand  # noqa: E402


pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux PTY test')


@pytest.mark.parametrize('reverse', [False, True])
def test_real_dual_process_config_readiness_and_clean_shutdown(tmp_path, monkeypatch, reverse):
    monkeypatch.setenv('ROS_DOMAIN_ID', '219')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    context = Context()
    rclpy.init(context=context)
    observer = Node('dual_process_observer', context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(observer)
    public_ready, private_ready = [], []
    observer.create_subscription(Bool, '/l20/hands_ready',
                                 lambda msg: public_ready.append(msg.data), ready_qos())
    observer.create_subscription(Bool, '/l20/startup/test_process',
                                 lambda msg: private_ready.append(msg.data), ready_qos())
    process = None
    log = tmp_path / 'dual-process.log'
    config = Path(__file__).resolve().parents[1] / 'config' / 'hand_identity.yaml'
    first_uid, second_uid = (RIGHT, LEFT) if reverse else (LEFT, RIGHT)
    try:
        with virtual_hand(first_uid, state_feedback=True) as (first, requests1), \
                virtual_hand(second_uid, state_feedback=True) as (second, requests2), \
                log.open('w') as output:
            left, right = (second, first) if reverse else (first, second)
            command = [sys.executable, '-c', 'from rm_l20_driver.dual_node import main; main()',
                       '--ros-args', '--params-file', str(config),
                       '-p', f'left_hand_port:={left}', '-p', f'right_hand_port:={right}',
                       '-r', '~/hands_ready:=/l20/startup/test_process']
            # Explicit PTY paths prevent enumeration or access to any physical port.
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and process.poll() is None:
                    executor.spin_once(timeout_sec=0.1)
                    if public_ready.count(True) >= 2 and private_ready.count(True) >= 2:
                        break
                assert public_ready.count(True) >= 2, log.read_text()
                assert private_ready.count(True) >= 2, log.read_text()
                names = observer.get_node_names()
                assert 'left_l20_driver' in names and 'right_l20_driver' in names
                assert requests1 and requests2
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    pytest.fail('dual process did not stop after SIGINT')
            assert process.returncode == 0, log.read_text()
            assert 'Traceback' not in log.read_text()
            for port in (first, second):
                with open_hand(port):
                    pass
    finally:
        executor.shutdown()
        observer.destroy_node()
        context.shutdown()
