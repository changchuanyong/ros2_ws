"""Exercise real pymodbus/pyserial RTU transport on a Linux virtual terminal."""

import os
import select
import struct
import sys
import threading
import time

import pytest

from rm_l20_driver.protocol import LinkerHandL20RS485


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith('linux'), reason='Linux PTY transport test')


def _rtu_frame(payload):
    return payload + struct.pack('<H', LinkerHandL20RS485.crc16(payload))


def _receive_request(master, count, stop, deadline):
    frame = bytearray()
    while len(frame) < count:
        if stop.is_set():
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('virtual slave timed out waiting for an RTU request')
        ready, _, _ = select.select([master], [], [], min(remaining, 0.05))
        if ready:
            chunk = os.read(master, count - len(frame))
            if not chunk:
                raise RuntimeError('virtual serial master reached EOF')
            frame.extend(chunk)
    assert frame[-2:] == _rtu_frame(frame[:-2])[-2:], 'invalid RTU request CRC'
    return bytes(frame)


def test_real_rtu_position_and_speed_round_trip_over_pty():
    """Check FC16/FC04 bytes and feedback using only /dev/pts virtual ports."""
    expected_positions = [
        11, 12, 13, 14, 15,
        6, 7, 8, 9, 10,
        1, 2, 3, 4, 5,
        0, 0, 0, 0, 0,
        0, 0, 0, 0, 0,
        16, 17, 18, 19, 20,
    ]
    stop = threading.Event()
    errors = []
    received = []
    master, slave = os.openpty()
    hand = None
    worker = None

    def virtual_slave():
        try:
            deadline = time.monotonic() + 3.0
            write = _receive_request(master, 69, stop, deadline)
            if write is None:
                return
            assert write[:7] == bytes([7, 0x10, 0, 0, 0, 30, 60])
            assert list(struct.unpack('>30H', write[7:-2])) == expected_positions
            received.append('position_write')
            acknowledgement = _rtu_frame(bytes([7, 0x10, 0, 0, 0, 30]))
            assert os.write(master, acknowledgement) == len(acknowledgement)

            for address, base in [(0, 100), (30, 200)]:
                request = _receive_request(master, 8, stop, deadline)
                if request is None:
                    return
                assert request[:6] == struct.pack('>BBHH', 7, 0x04, address, 30)
                received.append(address)
                reply = _rtu_frame(
                    bytes([7, 0x04, 60]) + struct.pack('>30H', *range(base, base + 30)))
                assert os.write(master, reply) == len(reply)
        except BaseException as error:
            errors.append(error)

    try:
        port = os.ttyname(slave)
        assert port.startswith('/dev/pts/'), 'test must only open a virtual serial port'
        worker = threading.Thread(target=virtual_slave, daemon=True)
        worker.start()
        hand = LinkerHandL20RS485(
            hand_id=7, modbus_port=port, timeout=0.25, retries=0, interval=0)
        hand.set_joint_positions(list(range(1, 21)))
        assert hand.get_state() == [
            110, 111, 112, 113, 114,
            105, 106, 107, 108, 109,
            100, 101, 102, 103, 104,
            125, 126, 127, 128, 129,
        ]
        assert hand.get_speed() == [
            210, 211, 212, 213, 214,
            205, 206, 207, 208, 209,
            200, 201, 202, 203, 204,
            225, 226, 227, 228, 229,
        ]
        worker.join(timeout=0.5)
        assert not worker.is_alive(), 'virtual slave did not finish'
        assert received == ['position_write', 0, 30]
    finally:
        stop.set()
        try:
            if hand is not None:
                hand.close()
        finally:
            if worker is not None:
                worker.join(timeout=0.5)
            os.close(slave)
            os.close(master)
        if worker is not None and worker.is_alive():
            raise RuntimeError('virtual slave thread was not cleaned up')
        if errors:
            raise AssertionError('virtual Modbus slave failed') from errors[0]
