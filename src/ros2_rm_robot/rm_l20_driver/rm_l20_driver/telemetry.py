"""Serialize optional raw telemetry and position writes on one serial owner."""

from collections import deque
import math
from numbers import Integral
import threading
import time


# Adjacent input registers share one response, reducing serial turnaround time.
BLOCKS = ((0, 90, (('position', 0, 30), ('speed', 30, 30), ('torque', 60, 30))),
          (150, 50, (('current', 150, 30), ('force', 180, 20))))


def validate_rates(rate, matrix_rate):
    """Reject invalid schedules before opening or transferring a serial port."""
    for name, value, maximum in (
            ('telemetry_rate', rate, 20), ('matrix_rate', matrix_rate, 10)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not (
                math.isfinite(value) and 0 < value <= maximum):
            raise ValueError(f'{name} must be finite and within (0, {maximum}] Hz')


def raw_registers(values, count):
    """Retain uint16 registers without clipping, signed decoding, or SI scaling."""
    if len(values) != count or any(
            isinstance(value, bool) or not isinstance(value, Integral) or
            not 0 <= value <= 65535 for value in values):
        raise ValueError(f'expected {count} uint16 feedback registers')
    return [int(value) for value in values]


class SerialTelemetryWorker:
    """Own the verified hand until close; yield between every Modbus transaction.

    Rates are requested maxima, not guarantees. Late acquisitions are skipped,
    and no frame is presented as a simultaneous sample of all register blocks.
    """

    def __init__(self, hand, *, side, uid, session_id, rate=10.0, matrix_rate=5.0,
                 command_gate=lambda: True, result_limit=1000):
        validate_rates(rate, matrix_rate)
        self.hand = hand
        self.identity = {'schema_version': 1, 'session_id': session_id,
                         'hand': side, 'uid': uid}
        self.rate = rate
        self.matrix_rate = matrix_rate
        self.command_gate = command_gate
        self.result_limit = result_limit
        self.failure = ''
        self.close_error = ''
        self._condition = threading.Condition()
        self._stopping = False
        self._command = None
        self._command_pending = False
        self._results = deque()
        self._seq = 0
        self._thread = None
        self._block_due = [0.0] * len(BLOCKS)
        self._matrix_due = 0.0
        self._matrix_phase = 0
        self._sensor = 1
        self._matrix_started = 0
        self._matrix_checks = 0
        self._rows = self._cols = 0
        self._active_field = 'startup'
        self._active_address = 0
        self._active_started = 0

    @property
    def alive(self):
        """Return whether the serial owner is still running."""
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Transfer serial ownership to one background thread."""
        if self._thread is not None:
            raise RuntimeError('serial telemetry worker already started')
        self._thread = threading.Thread(target=self._run, name='l20-serial', daemon=True)
        self._thread.start()

    def submit(self, positions, token):
        """Accept at most one pending or in-flight position command."""
        with self._condition:
            if self._stopping or self.failure or self._command_pending:
                return False
            self._command_pending = True
            self._command = (list(positions), token)
            self._condition.notify()
            return True

    def drain(self):
        """Move complete immutable results to the ROS thread without serial I/O."""
        with self._condition:
            result = list(self._results)
            self._results.clear()
            return result

    def stop(self, timeout=1.5):
        """Cancel queued work and wait for the admitted transaction and close."""
        with self._condition:
            self._stopping = True
            self._command = None
            self._condition.notify()
        if self._thread is None or self._thread.ident is None:
            self.hand.close()
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _packet(self, kind, field, address, started, values, **extra):
        self._seq += 1
        return {**self.identity, 'seq': self._seq, 'kind': kind, 'field': field,
                'started_ns': started, 'finished_ns': time.monotonic_ns(),
                'wall_time_ns': time.time_ns(), 'register_address': address,
                'values': values, 'valid': True, 'error': '', **extra}

    def _emit(self, packet, token=None):
        with self._condition:
            if len(self._results) >= self.result_limit:
                raise RuntimeError('telemetry result queue overflow; acquisition stopped')
            self._results.append((packet, token))

    def _admit(self, field, address):
        with self._condition:
            if self._stopping:
                return False
            if field != 'command' and self._command is not None:
                return False
            self._active_field, self._active_address = field, address
            self._active_started = time.monotonic_ns()
            return True

    def _matrix_step(self):
        if self._matrix_phase == 0:
            if not self._admit('matrix', 198):
                return
            self._matrix_started = self._active_started
            # Only select the read channel: no size, motion, or flash writes.
            self.hand._write_holding(198, [self._sensor], interval=self.hand.matrix_interval)
            self._matrix_checks = 0
            self._matrix_phase = 1
        elif self._matrix_phase == 1:
            if not self._admit('matrix', 223):
                return
            index, size = raw_registers(self.hand._read_input(
                223, 2, interval=self.hand.matrix_interval), 2)
            self._matrix_checks += 1
            if index != self._sensor:
                if self._matrix_checks >= 3:
                    raise RuntimeError('matrix sensor selection was not acknowledged')
                return
            self._rows, self._cols = (size >> 4) & 15, size & 15
            if size > 255 or not 0 < self._rows * self._cols <= 96:
                raise ValueError(f'invalid matrix dimensions register: {size}')
            self._matrix_phase = 2
        else:
            if not self._admit('matrix', 225):
                return
            count = self._rows * self._cols
            values = raw_registers(self.hand._read_input(
                225, count, interval=self.hand.matrix_interval), count)
            self._emit(self._packet(
                'touch', 'matrix', 225, self._matrix_started, values,
                sensor=self._sensor, rows=self._rows, cols=self._cols))
            self._sensor = self._sensor % 5 + 1
            self._matrix_phase = 0
            self._matrix_due = time.monotonic() + 1.0 / self.matrix_rate

    def _run(self):
        try:
            while True:
                with self._condition:
                    if self._stopping:
                        break
                    command, self._command = self._command, None
                if command is not None:
                    values, token = command
                    if not self._admit('command', 0):
                        continue
                    if not self.command_gate():
                        raise RuntimeError('command gate closed before serial write')
                    self.hand.set_joint_positions(values)
                    stamp = token.header.stamp
                    self._emit(self._packet(
                        'command_written', 'command', 0, self._active_started, values,
                        command_stamp={'sec': stamp.sec, 'nanosec': stamp.nanosec}), token)
                    with self._condition:
                        self._command_pending = False
                    continue
                now = time.monotonic()
                index = min(range(len(BLOCKS)), key=self._block_due.__getitem__)
                due = min(self._block_due[index], self._matrix_due)
                if due > now:
                    with self._condition:
                        if not self._stopping and self._command is None:
                            self._condition.wait(min(due - now, 0.05))
                    continue
                if self._block_due[index] <= self._matrix_due:
                    address, count, fields = BLOCKS[index]
                    if not self._admit('+'.join(field for field, _, _ in fields), address):
                        continue
                    values = raw_registers(self.hand._read_input(address, count), count)
                    finished, wall_time = time.monotonic_ns(), time.time_ns()
                    for field, field_address, field_count in fields:
                        offset = field_address - address
                        self._emit(self._packet(
                            'feedback', field, field_address, self._active_started,
                            values[offset:offset + field_count],
                            finished_ns=finished, wall_time_ns=wall_time))
                    self._block_due[index] = time.monotonic() + 1.0 / self.rate
                else:
                    self._matrix_step()
        except Exception as error:
            self.failure = f'{self._active_field} acquisition/write failed: {error}'
            packet = self._packet(
                'error', self._active_field, self._active_address,
                self._active_started, [], valid=False, error=self.failure)
            # Reserve the failure signal even if the consumer stopped draining.
            with self._condition:
                if len(self._results) >= self.result_limit:
                    self._results.pop()
                self._results.append((packet, None))
        finally:
            with self._condition:
                self._stopping = True
                self._command = None
                self._command_pending = False
            try:
                self.hand.close()
            except Exception as error:
                self.close_error = str(error)
