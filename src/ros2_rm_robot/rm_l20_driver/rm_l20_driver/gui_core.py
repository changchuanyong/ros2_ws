"""Validate GUI targets, preserve pose files, and gate manual hand commands."""

import math
import os
from collections.abc import Sequence
from numbers import Real
from pathlib import Path
import tempfile
import time

import yaml


SIDES = ('left', 'right')
RESERVED_SLOTS = (11, 12, 13, 14)
ACTIVE_SLOTS = tuple(index for index in range(20) if index not in RESERVED_SLOTS)
POSE_NAMES = ('READY', 'PRESS_C', 'PRESS_D', 'PRESS_E', 'PRESS_F', 'PRESS_G')
_FINGERS = ('拇指', '食指', '中指', '无名指', '小指')
JOINT_LABELS = tuple(
    f'{finger} {group}' + ('（预留）' if group == 'ROLL' and index else '')
    for group in ('ROOT', 'YAW', 'ROLL', 'TIP')
    for index, finger in enumerate(_FINGERS)
)
_SIDE_LABELS = {'left': '左手', 'right': '右手'}


def _values(values, maximum, label):
    """Accept numeric sequences without converting text or clipping values."""
    try:
        if (not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or
                len(values) != 20):
            raise ValueError(f'{label}必须包含 20 个数值')
        result = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(f'{label}必须是数值，不能是布尔值或字符串')
            number = float(value)
            if not math.isfinite(number) or not 0 <= number <= maximum:
                raise ValueError(f'{label}必须是 0–{maximum} 范围内的有限数值')
            result.append(number)
        return result
    except (TypeError, OverflowError) as error:
        raise ValueError(f'{label}必须包含 20 个有限数值') from error


def validate_target(values):
    """Return the complete 20 command slots in SDK order, including reserves."""
    return _values(values, 255, '目标姿态')


def feedback_target(values):
    """Use valid position feedback without copying meaningless reserved registers."""
    state = _values(values, 65535, '状态反馈')
    for index in ACTIVE_SLOTS:
        if state[index] > 255:
            raise ValueError(f'{JOINT_LABELS[index]} 位置反馈超出 0–255，不能用于滑块控制')
    return [0.0 if index in RESERVED_SLOTS else value
            for index, value in enumerate(state)]


def _pose_document(document):
    if not isinstance(document, dict) or not isinstance(document.get('poses'), dict):
        raise ValueError('姿态文件必须包含 poses 映射')
    if any(not isinstance(name, str) or not name.strip() for name in document['poses']):
        raise ValueError('姿态名称必须是非空字符串')
    return document


def load_pose_file(path):
    """Load a pose document without filling empty templates or changing files."""
    with Path(path).expanduser().open(encoding='utf-8') as stream:
        return _pose_document(yaml.safe_load(stream))


def read_pose(document, name):
    """Return a selected target and its explicit human verification flag."""
    entry = _pose_document(document)['poses'].get(name)
    if not isinstance(entry, dict):
        raise ValueError(f'{name}: 缺少姿态映射')
    if not isinstance(entry.get('verified'), bool):
        raise ValueError(f'{name}: verified 必须为 true 或 false')
    values = entry.get('positions')
    if isinstance(values, (list, tuple)) and not values:
        return [], entry['verified']
    return validate_target(values), entry['verified']


def save_pose(path, name, positions, verified=False, overwrite=False):
    """Atomically update one named target, preserving other poses and metadata."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError('姿态名称不能为空')
    if not isinstance(verified, bool):
        raise ValueError('verified 必须为 true 或 false')
    target = validate_target(positions)
    path = Path(path).expanduser()
    document = load_pose_file(path) if path.exists() else {'poses': {}}
    if name in document['poses'] and not overwrite:
        raise FileExistsError(f'姿态 {name} 已存在，覆盖前必须确认')
    entry = document['poses'].get(name)
    entry = dict(entry) if isinstance(entry, dict) else {}
    entry.update(positions=target, verified=verified)
    document['poses'][name] = entry
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=path.parent,
                prefix=f'.{path.name}.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(document, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return document


class ReadinessGate:
    """Latch lost readiness before a newly arrived packet can hide a timeout."""

    STATE_TIMEOUT = 0.5
    READY_TIMEOUT = 2.5

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.states = {}
        self.state_times = {}
        self.fault = ''
        self.ready = False
        self.ready_time = None
        self._seen_ready = False

    def _fail(self, reason):
        if not self.fault:
            self.fault = reason + '；请重新启动'

    def _check_timeouts(self, now):
        if self.fault:
            return
        if (self._seen_ready and self.ready_time is not None and
                now - self.ready_time > self.READY_TIMEOUT):
            self._fail('驱动就绪心跳超时')
            return
        for side in SIDES:
            timestamp = self.state_times.get(side)
            if timestamp is not None and now - timestamp > self.STATE_TIMEOUT:
                self._fail(f'{_SIDE_LABELS[side]}状态超时')
                return

    def update_ready(self, ready):
        """Accept startup false, but never recover from a later readiness loss."""
        now = self.clock()
        self._check_timeouts(now)
        if not isinstance(ready, bool):
            self._fail('驱动就绪消息无效')
            return
        if self._seen_ready and not ready:
            self._fail('驱动已失去就绪状态')
        self.ready = ready
        self.ready_time = now
        self._seen_ready = self._seen_ready or ready

    def update_state(self, side, values):
        """Keep raw feedback for display; an invalid sample disables both hands."""
        if side not in SIDES:
            raise ValueError('hand side must be left or right')
        now = self.clock()
        self._check_timeouts(now)
        try:
            state = _values(values, 65535, '状态反馈')
        except ValueError as error:
            self._fail(f'{_SIDE_LABELS[side]}状态无效：{error}')
            return
        self.states[side] = state
        self.state_times[side] = now
        try:
            feedback_target(state)
        except ValueError as error:
            self._fail(f'{_SIDE_LABELS[side]}状态无效：{error}')

    def reason(self, subscribers):
        """Return an empty reason only when both hands can accept commands now."""
        self._check_timeouts(self.clock())
        if self.fault:
            return self.fault
        if not self.ready:
            return '等待本次驱动就绪'
        for side in SIDES:
            if side not in self.state_times:
                return f'等待{_SIDE_LABELS[side]}状态反馈'
        for side in SIDES:
            if subscribers.get(side, 0) < 1:
                return f'等待{_SIDE_LABELS[side]}命令订阅'
        return ''
