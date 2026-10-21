"""Exercise the L20 RS485 wire contract without opening a serial device."""

import pytest

from rm_l20_driver import protocol


class FakeResponse:
    """Minimal pymodbus response supporting success and exception replies."""

    def __init__(self, registers=None, error=False):
        self.registers = registers
        self.error = error
        self.exception_code = 2 if error else None

    def isError(self):
        return self.error


class FakeClient:
    """Record wire requests; never access a serial port."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.connected = True
        self.connect_error = None
        self.close_count = 0
        self.response = FakeResponse(registers=list(range(30)))

    def connect(self):
        if self.connect_error is not None:
            raise self.connect_error
        return self.connected

    def close(self):
        self.close_count += 1

    def request(self, operation, kwargs):
        self.calls.append((operation, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def read_input_registers(self, **kwargs):
        return self.request('read_input', kwargs)

    def read_holding_registers(self, **kwargs):
        return self.request('read_holding', kwargs)

    def write_registers(self, **kwargs):
        return self.request('write_multiple', kwargs)

    def write_register(self, **kwargs):
        return self.request('write_single', kwargs)


@pytest.fixture
def client(monkeypatch):
    """Replace the constructor before any protocol instance can connect."""
    fake = FakeClient()

    def create_client(**kwargs):
        fake.kwargs = kwargs
        return fake

    monkeypatch.setattr(protocol, 'ModbusSerialClient', create_client)
    return fake


@pytest.fixture
def hand(client):
    device = protocol.LinkerHandL20RS485(
        hand_id=7, modbus_port='fake-port', interval=0, matrix_interval=0)
    yield device
    device.close()


def test_serial_configuration_does_not_send_an_initial_pose(hand, client):
    assert client.kwargs['port'] == 'fake-port'
    assert client.kwargs['baudrate'] == 115200
    assert client.kwargs['bytesize'] == 8
    assert client.kwargs['parity'] == 'N'
    assert client.kwargs['stopbits'] == 1
    assert client.calls == []


def test_position_command_uses_documented_register_order(hand, client):
    hand.set_joint_positions(list(range(1, 21)))

    assert client.calls == [('write_multiple', {
        'address': 0,
        'values': [
            11, 12, 13, 14, 15,       # ROLL (four reserved SDK slots retained)
            6, 7, 8, 9, 10,          # YAW
            1, 2, 3, 4, 5,           # ROOT1
            0, 0, 0, 0, 0,           # reserved ROOT2
            0, 0, 0, 0, 0,           # reserved ROOT3
            16, 17, 18, 19, 20,      # TIP
        ],
        'slave': 7,
    })]


def test_position_boundaries_are_not_wrapped(hand, client):
    hand.set_joint_positions([0.0] * 10 + [255.0] * 10)
    assert client.calls[0][1]['values'] == (
        [255] * 5 + [0] * 20 + [255] * 5)


def test_feedback_maps_registers_to_twenty_values(hand, client):
    client.response = FakeResponse(registers=[
        110, 111, 112, 113, 114,
        120, 121, 122, 123, 124,
        130, 131, 132, 133, 134,
        65000, 65001, 65002, 65003, 65004,
        65005, 65006, 65007, 65008, 65009,
        140, 141, 142, 143, 144,
    ])

    assert hand.get_state() == [
        130, 131, 132, 133, 134,
        120, 121, 122, 123, 124,
        110, 111, 112, 113, 114,
        140, 141, 142, 143, 144,
    ]
    assert client.calls == [(
        'read_input', {'address': 0, 'count': 30, 'slave': 7})]


@pytest.mark.parametrize('method,address', [
    ('get_speed', 30),
    ('get_torque', 60),
    ('get_fault', 90),
    ('get_temperature', 120),
    ('get_current', 150),
])
def test_feedback_reads_the_correct_input_block(hand, client, method, address):
    assert len(getattr(hand, method)()) == 20
    assert client.calls == [(
        'read_input', {'address': address, 'count': 30, 'slave': 7})]


def test_command_readback_uses_holding_registers(hand, client):
    assert hand.read_position_command() == list(range(30))
    assert client.calls == [(
        'read_holding', {'address': 0, 'count': 30, 'slave': 7})]


@pytest.mark.parametrize('values', [
    None, [], [0] * 5, [0] * 19, [0] * 21, [0] * 30,
    [-1] + [0] * 19, [256] + [0] * 19,
    [float('nan')] + [0] * 19,
    [float('inf')] + [0] * 19,
    [-float('inf')] + [0] * 19,
    ['invalid'] + [0] * 19,
])
def test_invalid_position_command_never_writes(hand, client, values):
    with pytest.raises((TypeError, ValueError)):
        hand.set_joint_positions(values)
    assert client.calls == []


@pytest.mark.parametrize('method', [
    'read_positions', 'read_position_command',
])
@pytest.mark.parametrize('count', [0, 29, 31])
def test_wrong_register_count_fails_before_using_feedback(
        hand, client, method, count):
    client.response = FakeResponse(registers=[0] * count)
    with pytest.raises(RuntimeError):
        getattr(hand, method)()


@pytest.mark.parametrize('method', [
    'read_positions', 'read_position_command',
])
@pytest.mark.parametrize('response', [None, FakeResponse(error=True)])
def test_error_or_absent_read_response_is_not_valid_feedback(
        hand, client, method, response):
    client.response = response
    with pytest.raises(RuntimeError):
        getattr(hand, method)()


@pytest.mark.parametrize('response', [None, FakeResponse(error=True)])
def test_failed_write_is_reported(hand, client, response):
    client.response = response
    with pytest.raises(RuntimeError):
        hand.set_joint_positions([0] * 20)


@pytest.mark.parametrize('operation', ['input', 'holding', 'write'])
def test_modbus_transport_errors_are_reported(hand, client, operation):
    client.response = protocol.ModbusException('simulated timeout')
    with pytest.raises(RuntimeError):
        if operation == 'input':
            hand.read_positions()
        elif operation == 'holding':
            hand.read_position_command()
        else:
            hand.set_joint_positions([0] * 20)


def test_failed_connection_closes_serial_client(client):
    client.connected = False
    with pytest.raises(ConnectionError):
        protocol.LinkerHandL20RS485(modbus_port='fake-port')
    assert client.close_count == 1
    assert client.calls == []


def test_connection_exception_closes_serial_client(client):
    client.connect_error = OSError('simulated serial error')
    with pytest.raises(OSError):
        protocol.LinkerHandL20RS485(modbus_port='fake-port')
    assert client.close_count == 1


@pytest.mark.parametrize('hand_id', [0, -1, 248, True, False, 1.5, '1', None])
def test_invalid_hand_id_is_rejected_before_creating_client(monkeypatch, hand_id):
    def unexpected_client(**kwargs):
        pytest.fail('invalid hand_id must not construct a serial client')

    monkeypatch.setattr(protocol, 'ModbusSerialClient', unexpected_client)
    with pytest.raises(ValueError):
        protocol.LinkerHandL20RS485(hand_id=hand_id, modbus_port='fake-port')


def test_close_is_idempotent(hand, client):
    hand.close()
    hand.close()
    assert client.close_count == 1
    assert hand.connected is False


@pytest.mark.parametrize('operation', ['input', 'holding', 'write', 'single_write'])
def test_closed_connection_does_not_send_requests(hand, client, operation):
    hand.close()
    with pytest.raises(RuntimeError, match='closed'):
        if operation == 'input':
            hand.get_state()
        elif operation == 'holding':
            hand.read_position_command()
        elif operation == 'write':
            hand.set_joint_positions([0] * 20)
        else:
            hand.set_device_id(3)
    assert client.calls == []


def test_context_manager_closes_after_exception(client):
    with pytest.raises(ValueError, match='caller failed'):
        with protocol.LinkerHandL20RS485(modbus_port='fake-port'):
            raise ValueError('caller failed')
    assert client.close_count == 1
