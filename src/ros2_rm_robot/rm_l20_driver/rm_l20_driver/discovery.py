"""Read-only UID discovery, retaining the exact connections that were verified."""

from dataclasses import dataclass
import os
import stat

from serial.tools import list_ports

from rm_l20_driver.protocol import LinkerHandL20RS485, decode_uid


class IdentityError(ValueError):
    """An identity is invalid, ambiguous, unstable, or assigned to the wrong side."""


@dataclass
class HandBinding:
    """A verified port and the still-open protocol connection."""

    port: str
    uid: str
    hand: LinkerHandL20RS485


def validate_uid(uid):
    """Require an exact, nonempty ASCII identity, without normalizing it."""
    if not isinstance(uid, str) or not uid or not all(33 <= ord(c) <= 126 for c in uid):
        raise IdentityError('expected UID must be nonempty printable ASCII without spaces')


def read_verified_uid(hand):
    """Read twice without writing any configuration or position register."""
    try:
        first = decode_uid(hand.read_uid_registers())
        second = decode_uid(hand.read_uid_registers())
    except ValueError as error:
        raise IdentityError(f'invalid UID: {error}') from error
    if first != second:
        raise IdentityError(f'unstable UID: {first!r} then {second!r}')
    return first


def open_hand(port, baudrate=115200, slave_id=1):
    """Open Linux serial exclusively, with bounded read requests and no retries."""
    return LinkerHandL20RS485(
        modbus_port=port, baudrate=baudrate, hand_id=slave_id,
        timeout=0.25, retries=0, exclusive=True)


def device_key(port):
    """Identify the actual device so aliases cannot select it twice."""
    info = os.stat(port)
    if not stat.S_ISCHR(info.st_mode):
        raise ValueError(f'{port} is not a character device')
    return info.st_rdev


def close_bindings(bindings, report):
    """Attempt every close even if one disconnected adapter raises."""
    for binding in bindings.values():
        try:
            binding.hand.close()
        except Exception as error:
            report(f'{binding.port}: close failed: {error}')


def discover_hands(expected, ports, *, baudrate=115200, slave_id=1, report=print):
    """Return one retained connection per expected UID, or release all and fail."""
    for side in ('left', 'right'):
        validate_uid(expected[side])
        if not ports[side]:
            raise IdentityError(f'{side}_hand_port must be auto or a serial path')
    if expected['left'] == expected['right']:
        raise IdentityError('left and right UIDs must differ')

    explicit = {side: device_key(port) for side, port in ports.items() if port != 'auto'}
    if len(explicit) == 2 and explicit['left'] == explicit['right']:
        raise IdentityError('left and right ports refer to the same device')
    candidates = {device_key(ports[side]): ports[side] for side in explicit}
    if 'auto' in ports.values():
        for entry in sorted(list_ports.comports(), key=lambda item: item.device):
            if (entry.vid, entry.pid) != (0x1A86, 0x7523):
                continue
            try:
                candidates.setdefault(device_key(entry.device), entry.device)
            except OSError as error:
                report(f'{entry.device}: cannot inspect port: {error}')

    matched = {}
    try:
        for key, port in candidates.items():
            hand = None
            try:
                hand = open_hand(port, baudrate, slave_id)
                uid = read_verified_uid(hand)
                report(f'{port}: UID={uid}')
                for side, explicit_key in explicit.items():
                    if explicit_key == key and uid != expected[side]:
                        raise IdentityError(f'{side} port {port}: expected {expected[side]}, got {uid}')
                side = next((side for side, value in expected.items() if value == uid), None)
                if side is None:
                    report(f'{port}: unconfigured UID ignored')
                    continue
                if side in matched:
                    raise IdentityError(f'duplicate UID {uid} at {matched[side].port} and {port}')
                if side in explicit and explicit[side] != key:
                    raise IdentityError(f'{uid} found outside the specified {side} port')
                matched[side] = HandBinding(port, uid, hand)
                hand = None  # Ownership transferred; do not reopen this connection.
            except IdentityError:
                raise
            except Exception as error:
                report(f'{port}: UID read failed (busy, permission, or communication): {error}')
                if key in explicit.values():
                    raise RuntimeError(f'cannot verify explicitly selected port {port}') from error
            finally:
                if hand is not None:
                    hand.close()
        missing = set(expected) - set(matched)
        if missing:
            raise IdentityError('missing configured hand(s): ' + ', '.join(sorted(missing)))
        return matched
    except BaseException:
        close_bindings(matched, report)
        raise
