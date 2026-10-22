"""Verify identity discovery and exclusive ownership over Linux PTYs, never USB."""

from contextlib import contextmanager
import os
import select
import struct
import sys
import threading

import pytest

from rm_l20_driver.discovery import close_bindings, discover_hands, open_hand, read_verified_uid
from rm_l20_driver.protocol import LinkerHandL20RS485


pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux PTY test')
LEFT = 'LHT20-011-260-L-B-1-D'
RIGHT = 'LHT20-011-266-R-B-1-D'


def frame(payload):
    return payload + struct.pack('<H', LinkerHandL20RS485.crc16(payload))


@contextmanager
def virtual_hand(uid, bad_crc=False, state_feedback=False):
    master, slave = os.openpty()
    port = os.ttyname(slave)
    assert port.startswith('/dev/pts/')
    stop = threading.Event()
    requests, errors = [], []
    registers = struct.unpack('<11H', uid.encode('ascii').ljust(22, b'\x00'))

    def worker():
        buffer = bytearray()
        try:
            while not stop.is_set():
                readable, _, _ = select.select([master], [], [], 0.05)
                if not readable:
                    continue
                buffer.extend(os.read(master, 256))
                while len(buffer) >= 8:
                    request = bytes(buffer[:8])
                    del buffer[:8]
                    requests.append(request)
                    assert request == frame(request[:-2])
                    slave_id, function, address, count = struct.unpack('>BBHH', request[:-2])
                    assert slave_id == 1 and function == 4  # No writes permitted.
                    if address == 212 and count == 11:
                        values = registers
                    else:
                        assert state_feedback and address in (0, 30) and count == 30
                        values = list(range(30))
                    reply = frame(bytes([1, 4, 2 * count]) + struct.pack(f'>{count}H', *values))
                    if bad_crc:
                        reply = reply[:-1] + bytes([reply[-1] ^ 0xFF])
                    os.write(master, reply)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        yield port, requests
    finally:
        stop.set()
        thread.join(timeout=1)
        os.close(slave)
        os.close(master)
        assert not thread.is_alive()
        if errors:
            raise AssertionError('virtual hand failed') from errors[0]


def test_real_uid_discovery_keeps_both_exclusive_connections():
    with virtual_hand(RIGHT) as (right_port, right_reads), virtual_hand(LEFT) as (left_port, left_reads):
        bindings = discover_hands(
            {'left': LEFT, 'right': RIGHT}, {'left': left_port, 'right': right_port})
        try:
            assert bindings['left'].uid == LEFT and bindings['left'].port == left_port
            assert bindings['right'].uid == RIGHT and bindings['right'].port == right_port
            assert len(left_reads) == len(right_reads) == 2
            with pytest.raises((ConnectionError, OSError)):
                open_hand(left_port)
            assert len(left_reads) == 2  # A competing open must not send requests.
            assert read_verified_uid(bindings['right'].hand) == RIGHT
        finally:
            close_bindings(bindings, print)
        # Ownership must be released even while the PTY itself continues to exist.
        with open_hand(left_port) as hand:
            assert read_verified_uid(hand) == LEFT


def test_bad_crc_never_produces_uid_and_does_not_retry():
    with virtual_hand(LEFT, bad_crc=True) as (port, requests):
        with open_hand(port) as hand:
            with pytest.raises(RuntimeError):
                read_verified_uid(hand)
            assert hand.cli.connect() is False  # A failed transport cannot reopen itself.
        assert len(requests) == 1
        with open_hand(port):
            pass


def test_wrong_manual_side_closes_both_connections():
    with virtual_hand(LEFT) as (left_port, _), virtual_hand(RIGHT) as (right_port, _):
        with pytest.raises(ValueError, match='expected'):
            discover_hands({'left': LEFT, 'right': RIGHT}, {'left': right_port, 'right': left_port})
        with open_hand(right_port) as hand:
            assert read_verified_uid(hand) == RIGHT


def test_right_only_retains_exclusive_verified_pty():
    with virtual_hand(RIGHT) as (port, requests):
        bindings = discover_hands({'right': RIGHT}, {'right': port})
        try:
            assert set(bindings) == {'right'} and len(requests) == 2
            with pytest.raises(RuntimeError, match='cannot verify'):
                discover_hands({'right': RIGHT}, {'right': port})
            assert len(requests) == 2
        finally:
            close_bindings(bindings, print)
        with open_hand(port) as hand:
            assert read_verified_uid(hand) == RIGHT


def test_right_only_wrong_uid_releases_pty():
    with virtual_hand(LEFT) as (port, requests):
        with pytest.raises(ValueError, match='expected'):
            discover_hands({'right': RIGHT}, {'right': port})
        assert len(requests) == 2
        with open_hand(port) as hand:
            assert read_verified_uid(hand) == LEFT
