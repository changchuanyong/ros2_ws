"""Use the two captured hardware replies to test identity without physical IO."""

import struct
from types import SimpleNamespace

import pytest

from rm_l20_driver import discovery
from rm_l20_driver.protocol import decode_uid


LEFT = 'LHT20-011-260-L-B-1-D'
RIGHT = 'LHT20-011-266-R-B-1-D'
CAPTURED = [
    ('48 4c 32 54 2d 30 31 30 2d 31 36 32 2d 30 2d 4c 2d 42 2d 31 00 44', LEFT),
    ('48 4c 32 54 2d 30 31 30 2d 31 36 32 2d 36 2d 52 2d 42 2d 31 00 44', RIGHT),
]


def words(uid):
    raw = uid.encode('ascii').ljust(22, b'\x00')
    return list(struct.unpack('<11H', raw))


@pytest.mark.parametrize('raw,expected', CAPTURED)
def test_captured_uid_byte_order(raw, expected):
    assert decode_uid(list(struct.unpack('>11H', bytes.fromhex(raw)))) == expected


@pytest.mark.parametrize('registers', [
    [], [0] * 10, [0] * 12, [0] * 11, [256] + [0] * 10,
    [255] + [0] * 10, [-1] + [0] * 10, [65536] + [0] * 10,
    words('A\x00B'), words('A B'), words('ABC\n'), [True] + [0] * 10,
])
def test_invalid_uid_is_rejected(registers):
    with pytest.raises(ValueError):
        decode_uid(registers)


def test_uid_padding_and_full_length():
    assert decode_uid(words('ABC')) == 'ABC'
    assert decode_uid(words('A' * 22)) == 'A' * 22


class FakeHand:
    def __init__(self, *uids):
        self.uids = list(uids)
        self.reads = 0
        self.closed = 0

    def read_uid_registers(self):
        value = self.uids[min(self.reads, len(self.uids) - 1)]
        self.reads += 1
        if isinstance(value, Exception):
            raise value
        return words(value)

    def close(self):
        self.closed += 1


@pytest.fixture
def environment(monkeypatch):
    devices = {}
    opened = []
    aliases = {}
    monkeypatch.setattr(discovery, 'device_key', lambda port: aliases.get(port, port))
    monkeypatch.setattr(discovery.list_ports, 'comports', lambda: [
        SimpleNamespace(device=port, vid=0x1A86, pid=0x7523) for port in devices])

    def open_device(port, baudrate, slave_id):
        opened.append(port)
        assert (baudrate, slave_id) == (115200, 1)
        value = devices[port]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(discovery, 'open_hand', open_device)

    def discover(**ports):
        return discovery.discover_hands(
            {'left': LEFT, 'right': RIGHT},
            {'left': 'auto', 'right': 'auto', **ports}, report=lambda text: None)

    return devices, opened, aliases, discover


@pytest.mark.parametrize('ports', [('/dev/ttyUSB0', '/dev/ttyUSB1'),
                                   ('/dev/ttyUSB9', '/dev/ttyUSB2')])
def test_reordering_keeps_exact_connections(environment, ports):
    devices, opened, _, discover = environment
    left_port, right_port = ports
    left, right = FakeHand(LEFT), FakeHand(RIGHT)
    devices[right_port], devices[left_port] = right, left
    result = discover()
    assert result['left'].hand is left and result['left'].port == left_port
    assert result['right'].hand is right and result['right'].port == right_port
    assert sorted(opened) == sorted(ports)
    assert left.closed == right.closed == 0
    assert left.reads == right.reads == 2
    discovery.close_bindings(result, print)
    assert left.closed == right.closed == 1


def test_unrelated_timeout_and_permission_ports_do_not_get_bound(environment):
    devices, _, _, discover = environment
    devices.update(a=FakeHand('OTHER'), b=FakeHand(TimeoutError()),
                   c=PermissionError('denied'), d=FakeHand(LEFT), e=FakeHand(RIGHT))
    result = discover()
    assert set(result) == {'left', 'right'}
    assert devices['a'].closed == devices['b'].closed == 1
    discovery.close_bindings(result, print)


@pytest.mark.parametrize('extra', [FakeHand(LEFT), FakeHand(LEFT, RIGHT), FakeHand('')])
def test_duplicate_unstable_or_invalid_uid_closes_everything(environment, extra):
    devices, _, _, discover = environment
    devices.update(a=FakeHand(LEFT), b=FakeHand(RIGHT), c=extra)
    with pytest.raises(discovery.IdentityError):
        discover()
    assert all(hand.closed == 1 for hand in devices.values())


def test_missing_peer_closes_retained_hand(environment):
    devices, _, _, discover = environment
    devices['a'] = FakeHand(LEFT)
    with pytest.raises(discovery.IdentityError, match='right'):
        discover()
    assert devices['a'].closed == 1


def test_alias_is_probed_only_once(environment):
    devices, opened, aliases, discover = environment
    devices.update(a=FakeHand(LEFT), b=FakeHand(RIGHT))
    aliases['alias'] = 'a'
    devices['alias'] = devices['a']
    result = discover()
    assert opened == ['a', 'b']
    discovery.close_bindings(result, print)


def test_manual_reversed_ports_are_rejected(environment):
    devices, _, _, _ = environment
    devices.update(a=FakeHand(RIGHT), b=FakeHand(LEFT))
    with pytest.raises(discovery.IdentityError, match='expected'):
        discovery.discover_hands({'left': LEFT, 'right': RIGHT}, {'left': 'a', 'right': 'b'})
    assert devices['a'].closed == 1
    assert devices['b'].reads == 0


@pytest.mark.parametrize('expected,ports', [
    ({'left': LEFT, 'right': LEFT}, {'left': 'auto', 'right': 'auto'}),
    ({'left': '', 'right': RIGHT}, {'left': 'auto', 'right': 'auto'}),
    ({'left': LEFT, 'right': RIGHT}, {'left': 'a', 'right': 'alias'}),
])
def test_invalid_config_does_not_open_ports(environment, expected, ports):
    _, opened, aliases, _ = environment
    aliases['alias'] = 'a'
    with pytest.raises(discovery.IdentityError):
        discovery.discover_hands(expected, ports)
    assert opened == []


def test_manual_ports_do_not_scan_other_adapters(environment):
    devices, opened, _, _ = environment
    devices.update(a=FakeHand(LEFT), b=FakeHand(RIGHT), c=FakeHand(LEFT))
    result = discovery.discover_hands(
        {'left': LEFT, 'right': RIGHT}, {'left': 'a', 'right': 'b'})
    assert opened == ['a', 'b']
    discovery.close_bindings(result, print)
