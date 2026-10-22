"""Restart the installed GUI launch against two read-only PTYs, never USB."""

import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

import pytest

rclpy = pytest.importorskip('rclpy')
pytest.importorskip('PyQt5.QtWidgets')
from rclpy.context import Context  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402

from rm_l20_driver.discovery import open_hand  # noqa: E402
from rm_l20_driver.dual_node import ready_qos  # noqa: E402
from test_uid_transport import LEFT, RIGHT, virtual_hand  # noqa: E402


pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux PTY test')
_PROCESS_STARTED = re.compile(
    r'\[(l20_hand_gui|l20_dual_rs485_driver)-\d+\]: process started with pid \[(\d+)\]')


def _running(pid):
    """Treat a reaped or zombie child as stopped when checking cleanup."""
    try:
        status = Path(f'/proc/{pid}/stat').read_text()
    except FileNotFoundError:
        return False
    return status.rsplit(')', 1)[1].split()[0] != 'Z'


def _cleanup(process, child_pids):
    """Bound cleanup to this test's newly created process group, even on failure."""
    for signum, timeout in ((signal.SIGINT, 5), (signal.SIGTERM, 2), (signal.SIGKILL, 2)):
        if process.poll() is not None and not any(_running(pid) for pid in child_pids):
            return
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass
        for pid in child_pids:
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            process.poll()
            if process.returncode is not None and not any(_running(pid) for pid in child_pids):
                return
            time.sleep(0.05)
    if process.poll() is None:
        process.wait(timeout=2)


@pytest.mark.parametrize('first_exit', ['l20_hand_gui', 'l20_dual_rs485_driver'])
def test_installed_gui_launch_restarts_same_ptys_and_releases_ports(
        tmp_path, monkeypatch, first_exit):
    """Either child ending shuts down its peer; a second launch needs no replug."""
    ros2 = shutil.which('ros2')
    assert ros2, 'source ROS Humble and the built workspace before this integration test'
    monkeypatch.setenv('ROS_DOMAIN_ID', '221' if first_exit == 'l20_hand_gui' else '222')
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('RCUTILS_COLORIZED_OUTPUT', '0')
    monkeypatch.setenv('PYTHONUNBUFFERED', '1')
    monkeypatch.setenv('ROS_LOG_DIR', str(tmp_path / 'ros-logs'))
    context = Context()
    rclpy.init(context=context)
    observer = Node('gui_launch_observer', context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(observer)
    ready = []
    states = {'left': [], 'right': []}
    observer.create_subscription(Bool, '/l20/hands_ready',
                                 lambda message: ready.append(message.data), ready_qos())
    for side in states:
        observer.create_subscription(
            JointState, f'/cb_{side}_hand_state',
            lambda message, side=side: states[side].append(list(message.position)), 10)
    config = Path(__file__).resolve().parents[1] / 'config' / 'hand_identity.yaml'
    second_exit = ('l20_dual_rs485_driver' if first_exit == 'l20_hand_gui'
                   else 'l20_hand_gui')
    try:
        with virtual_hand(LEFT, state_feedback=True) as (left_port, left_requests), \
                virtual_hand(RIGHT, state_feedback=True) as (right_port, right_requests):
            assert left_port.startswith('/dev/pts/') and right_port.startswith('/dev/pts/')
            for round_index, exit_name in enumerate((first_exit, second_exit), start=1):
                ready.clear()
                for samples in states.values():
                    samples.clear()
                before_reads = (len(left_requests), len(right_requests))
                log = tmp_path / f'gui-round-{round_index}.log'
                pids = {}
                with log.open('w') as output:
                    process = subprocess.Popen(
                        [ros2, 'launch', 'rm_l20_driver', 'l20_dual_rs485.launch.py',
                         'use_gui:=true', f'left_hand_port:={left_port}',
                         f'right_hand_port:={right_port}', f'hand_identity_config:={config}'],
                        stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        deadline = time.monotonic() + 20
                        while time.monotonic() < deadline and process.poll() is None:
                            executor.spin_once(timeout_sec=0.1)
                            text = log.read_text(errors='replace')
                            pids = {name: int(pid) for name, pid in _PROCESS_STARTED.findall(text)}
                            if (len(pids) == 2 and ready.count(True) >= 2 and
                                    all(len(samples) >= 10 for samples in states.values())):
                                break
                        text = log.read_text(errors='replace')
                        assert process.poll() is None, text
                        assert set(pids) == {'l20_hand_gui', 'l20_dual_rs485_driver'}, text
                        assert ready.count(True) >= 2, text
                        assert all(len(samples) >= 10 for samples in states.values()), text
                        assert all(len(sample) == 20 for samples in states.values()
                                   for sample in samples), text
                        assert all(_running(pid) for pid in pids.values()), text
                        # This only terminates a known child; the test never creates a
                        # position-command publisher. Qt closeEvent has its own UI test.
                        os.kill(pids[exit_name], signal.SIGINT)
                        process.wait(timeout=10)
                        text = log.read_text(errors='replace')
                        assert process.returncode == 0, text
                        assert 'Traceback' not in text, text
                        assert not any(_running(pid) for pid in pids.values()), text
                    finally:
                        # Capture any child PID logged just before a failure, too.
                        text = log.read_text(errors='replace')
                        pids.update({name: int(pid)
                                     for name, pid in _PROCESS_STARTED.findall(text)})
                        _cleanup(process, tuple(pids.values()))
                assert len(left_requests) > before_reads[0]
                assert len(right_requests) > before_reads[1]
                assert all(request[1] == 4 for request in left_requests + right_requests)
                for port in (left_port, right_port):
                    with open_hand(port):
                        pass
    finally:
        executor.shutdown()
        observer.destroy_node()
        context.shutdown()
