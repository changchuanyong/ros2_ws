"""Exercise the installed single-hand launch against a Linux PTY, never USB."""

from contextlib import contextmanager
import json
import os
import re
import select
import signal
import struct
import subprocess
import sys
import threading
import time

import pytest
import yaml

from ament_index_python.packages import get_package_share_directory
from rm_l20_driver.protocol import LinkerHandL20RS485


pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux PTY test')
MELODY = ('E', 'E', 'F', 'G', 'G', 'F', 'E', 'D', 'C', 'C', 'D', 'E', 'E', 'D', 'D')


def rtu_frame(payload):
    return payload + struct.pack('<H', LinkerHandL20RS485.crc16(payload))


@contextmanager
def virtual_right_hand(uid):
    """Permit UID/state reads and position writes, rejecting all other registers."""
    master, slave = os.openpty()
    port = os.ttyname(slave)
    assert port.startswith('/dev/pts/')
    stopped = threading.Event()
    commands, requests, errors = [], [], []
    uid_words = struct.unpack('<11H', uid.encode('ascii').ljust(22, b'\x00'))

    def respond():
        buffer = bytearray()
        positions = [0] * 30
        try:
            while not stopped.is_set():
                readable, _, _ = select.select([master], [], [], 0.05)
                if not readable:
                    continue
                buffer.extend(os.read(master, 256))
                while len(buffer) >= 2:
                    function = buffer[1]
                    assert function in (4, 16), 'unexpected Modbus function'
                    if function == 16 and len(buffer) < 7:
                        break
                    size = 8 if function == 4 else 9 + buffer[6]
                    if len(buffer) < size:
                        break
                    request = bytes(buffer[:size])
                    del buffer[:size]
                    assert request == rtu_frame(request[:-2]), 'bad request CRC'
                    unit, _, address, count = struct.unpack('>BBHH', request[:6])
                    assert unit == 1
                    requests.append((function, address, count))
                    if function == 4:
                        if (address, count) == (212, 11):
                            values = uid_words
                        else:
                            assert address in (0, 30) and count == 30
                            values = positions if address == 0 else [0] * 30
                        response = rtu_frame(
                            bytes([1, 4, 2 * count]) + struct.pack(f'>{count}H', *values))
                    else:
                        assert (address, count, request[6]) == (0, 30, 60)
                        positions = list(struct.unpack('>30H', request[7:-2]))
                        # Decode independently of the driver's SDK_TO_REG mapping.
                        command = positions[10:15] + positions[5:10]
                        command += positions[0:5] + positions[25:30]
                        commands.append((time.monotonic(), command))
                        response = rtu_frame(request[:6])
                    assert os.write(master, response) == len(response)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=respond, daemon=True)
    worker.start()
    try:
        yield port, commands, requests
    finally:
        stopped.set()
        worker.join(timeout=1)
        os.close(slave)
        os.close(master)
        assert not worker.is_alive(), 'virtual hand thread did not stop'
        if errors:
            raise AssertionError('virtual hand received an invalid request') from errors[0]


def run_installed_launch(tmp_path, arguments):
    """Bound subprocess lifetime and stop its entire group on every failure."""
    log = tmp_path / 'launch.log'
    environment = dict(os.environ, ROS_DOMAIN_ID='221', ROS_LOCALHOST_ONLY='1')
    process = None
    with log.open('w') as output:
        try:
            process = subprocess.Popen(
                ['ros2', 'launch', 'rm_piano_player', 'l20_right_hand_piano.launch.py',
                 *arguments], env=environment, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True)
            try:
                returncode = process.wait(timeout=35)
            except subprocess.TimeoutExpired:
                pytest.fail('single-hand launch did not exit automatically:\n' + log.read_text())
            assert returncode == 0, log.read_text()
            # A normal launch must reap its driver and player, not leave serial owners.
            with pytest.raises(ProcessLookupError):
                os.killpg(process.pid, 0)
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                # A dead launcher can still have surviving children in its group.
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
    return log.read_text()


def started_executables(log):
    return re.findall(r'\[INFO\] \[([^\]]+)\]: process started with pid', log)


def status_messages(log):
    messages = []
    for line in log.splitlines():
        beginning = line.find('{"phase":')
        if beginning != -1:
            messages.append(json.loads(line[beginning:]))
    return messages


def test_installed_dry_run_starts_only_player_and_never_opens_pty(tmp_path):
    with virtual_right_hand('UNUSED') as (port, commands, requests):
        log = run_installed_launch(tmp_path, [f'hand_port:={port}', 'mode:=melody'])
        assert commands == requests == []
        started = started_executables(log)
        assert len(started) == 1 and started[0].startswith('l20_right_hand_piano.py-'), log
        statuses = status_messages(log)
        assert len(statuses) == 1 and statuses[0]['phase'] == 'dry_run', log
        assert statuses[0]['execute'] is False
        assert statuses[0]['melody'] == list(MELODY)
        assert all(not entry['valid'] and not entry['verified']
                   for entry in statuses[0]['calibration'].values())
        with LinkerHandL20RS485(modbus_port=port, exclusive=True):
            pass


def test_installed_melody_reaches_only_right_pty_and_releases_port(tmp_path):
    driver_share = get_package_share_directory('rm_l20_driver')
    identity_path = os.path.join(driver_share, 'config', 'hand_identity.yaml')
    with open(identity_path, encoding='utf-8') as stream:
        identity = yaml.safe_load(stream)
    right_uid = identity['l20_dual_rs485_driver']['ros__parameters']['right_hand_uid']
    names = ('READY', 'PRESS_C', 'PRESS_D', 'PRESS_E', 'PRESS_F', 'PRESS_G')
    # Synthetic targets exist only in this PTY test; they are not hardware calibration.
    poses = {name: [10 * (index + 1) + joint for joint in range(20)]
             for index, name in enumerate(names)}
    config = tmp_path / 'virtual_poses.yaml'
    config.write_text(yaml.safe_dump({'poses': {
        name: {'positions': values, 'verified': True} for name, values in poses.items()
    }}), encoding='utf-8')
    with virtual_right_hand(right_uid) as (port, commands, requests):
        assert port.startswith('/dev/pts/')
        log = run_installed_launch(tmp_path, [
            'execute:=true', 'mode:=melody', f'pose_config:={config}', f'hand_port:={port}',
            'ready_settle:=0.1', 'press_duration:=0.1', 'release_duration:=0.1',
        ])
        started = started_executables(log)
        assert len(started) == 2, log
        assert any(name.startswith('l20_rs485_driver-') for name in started), log
        assert any(name.startswith('l20_right_hand_piano.py-') for name in started), log
        expected = [poses['READY']]
        for note in MELODY:
            expected.extend((poses['PRESS_' + note], poses['READY']))
        assert [values for _, values in commands] == expected, log
        assert len(commands) == 31 and commands[-1][1] == poses['READY']
        assert all(later[0] - earlier[0] >= 0.1 - 1e-6
                   for earlier, later in zip(commands, commands[1:]))
        assert requests.count((4, 212, 11)) == 2  # No reopen or duplicate discovery.
        statuses = status_messages(log)
        assert statuses[-1]['phase'] == 'completed', log
        assert statuses[-1]['target_pose'] == 'READY' and statuses[-1]['note_index'] == 15
        assert not statuses[-1]['awaiting_write'] and statuses[-1]['written_at'] is not None
        assert statuses[-1]['progress_means'] == 'position_commands_only'
        # Verify the command scheduler's complete release intervals, including E/E and C/C.
        presses = [state for state in statuses
                   if state['phase'] == 'pressing' and state['awaiting_write']]
        releases = [state for state in statuses
                    if state['phase'] == 'releasing' and not state['awaiting_write']]
        assert len(presses) == len(releases) == 15
        for index in range(1, 15):
            assert presses[index]['sent_at'] - releases[index - 1]['written_at'] >= 0.1 - 1e-6
        with LinkerHandL20RS485(modbus_port=port, exclusive=True):
            pass
