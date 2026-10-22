"""Exercise manual-target validation, loss detection, and atomic pose updates."""

from array import array
from pathlib import Path

import pytest
import yaml

from rm_l20_driver import gui_core
from rm_l20_driver.gui_core import (
    ACTIVE_SLOTS, JOINT_LABELS, POSE_NAMES, RESERVED_SLOTS, ReadinessGate,
    feedback_target, load_pose_file, read_pose,
    save_pose, validate_target,
)


@pytest.mark.parametrize('values', [
    [], [0] * 19, [0] * 21, None, '0' * 20, set(range(20)), dict.fromkeys(range(20)),
    [0] * 19 + [True], [0] * 19 + ['20'], [0] * 19 + [None],
    [0] * 19 + [-1], [0] * 19 + [256], [0] * 19 + [float('nan')],
    [0] * 19 + [float('inf')], [0] * 19 + [float('-inf')],
    [0] * 19 + [10 ** 1000],
])
def test_invalid_targets_are_rejected_without_clipping(values):
    with pytest.raises(ValueError):
        validate_target(values)


def test_targets_keep_sdk_slot_order_and_fractional_values():
    target = [0, 255, 12.5, 1] * 5
    assert validate_target(target) == target
    assert len(JOINT_LABELS) == 20
    assert all('ROOT' in label for label in JOINT_LABELS[:5])
    assert all('YAW' in label for label in JOINT_LABELS[5:10])
    assert '拇指' in JOINT_LABELS[10] and '预留' not in JOINT_LABELS[10]
    assert all('预留' in label for label in JOINT_LABELS[11:15])
    assert all('TIP' in label for label in JOINT_LABELS[15:])


def test_existing_piano_template_loads_without_inventing_targets():
    path = (Path(__file__).resolve().parents[2] / 'rm_piano_player' /
            'config' / 'right_hand_ode_to_joy.yaml')
    document = load_pose_file(path)
    for name in POSE_NAMES:
        assert read_pose(document, name) == ([], False)


@pytest.mark.parametrize('document', [None, [], {}, {'poses': []}, {'poses': {1: {}}}])
def test_invalid_pose_documents_are_rejected(tmp_path, document):
    path = tmp_path / 'poses.yaml'
    path.write_text(yaml.safe_dump(document), encoding='utf-8')
    with pytest.raises(ValueError):
        load_pose_file(path)


@pytest.mark.parametrize('entry', [
    None, [], {}, {'positions': [0] * 20},
    {'positions': [0] * 20, 'verified': 'false'},
    {'positions': [0] * 20, 'verified': 1},
    {'positions': [256] * 20, 'verified': False},
])
def test_read_pose_rejects_malformed_entries(entry):
    with pytest.raises(ValueError):
        read_pose({'poses': {'READY': entry}}, 'READY')


def test_read_pose_reports_missing_name():
    with pytest.raises(ValueError):
        read_pose({'poses': {}}, 'READY')


def test_save_requires_complete_target_and_explicit_verification(tmp_path):
    path = tmp_path / 'right.yaml'
    with pytest.raises(ValueError):
        save_pose(path, 'READY', [])
    assert not path.exists()
    save_pose(path, 'READY', [12.5] * 20)
    assert read_pose(load_pose_file(path), 'READY') == ([12.5] * 20, False)
    with pytest.raises(FileExistsError):
        save_pose(path, 'READY', [1] * 20, verified=True)
    assert read_pose(load_pose_file(path), 'READY')[1] is False
    save_pose(path, 'READY', [12.5] * 20, verified=True, overwrite=True)
    assert read_pose(load_pose_file(path), 'READY')[1] is True
    save_pose(path, 'READY', [13] * 20, overwrite=True)
    assert read_pose(load_pose_file(path), 'READY')[1] is False


@pytest.mark.parametrize('name,verified', [('', False), ('  ', False), (None, False),
                                        ('READY', 'false'), ('READY', 1)])
def test_save_rejects_invalid_name_or_verification(tmp_path, name, verified):
    with pytest.raises(ValueError):
        save_pose(tmp_path / 'poses.yaml', name, [0] * 20, verified=verified)


def test_save_preserves_other_poses_and_document_metadata(tmp_path):
    path = tmp_path / 'right.yaml'
    original = {'description': '实机标定', 'poses': {
        'READY': {'positions': [1] * 20, 'verified': True, 'note': 'manual'},
        'PRESS_C': {'positions': [], 'verified': False},
    }}
    path.write_text(yaml.safe_dump(original, allow_unicode=True), encoding='utf-8')
    save_pose(path, 'READY', [2] * 20, overwrite=True)
    saved = load_pose_file(path)
    assert saved['description'] == original['description']
    assert saved['poses']['PRESS_C'] == original['poses']['PRESS_C']
    assert saved['poses']['READY']['note'] == 'manual'
    assert saved['poses']['READY']['verified'] is False


@pytest.mark.parametrize('stage', ['dump', 'replace'])
def test_save_failure_keeps_original_and_cleans_temporary_file(tmp_path, monkeypatch, stage):
    path = tmp_path / 'right.yaml'
    save_pose(path, 'READY', [1] * 20)
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError('injected write failure')

    if stage == 'dump':
        monkeypatch.setattr(gui_core.yaml, 'safe_dump', fail)
    else:
        monkeypatch.setattr(gui_core.os, 'replace', fail)
    with pytest.raises(OSError, match='injected'):
        save_pose(path, 'READY', [2] * 20, overwrite=True)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_malformed_existing_file_is_never_replaced(tmp_path):
    path = tmp_path / 'right.yaml'
    path.write_text('poses: [broken', encoding='utf-8')
    before = path.read_bytes()
    with pytest.raises(yaml.YAMLError):
        save_pose(path, 'READY', [1] * 20, overwrite=True)
    assert path.read_bytes() == before


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def live_gate():
    clock = Clock()
    gate = ReadinessGate(clock)
    gate.update_ready(True)
    gate.update_state('left', [1] * 20)
    gate.update_state('right', [2] * 20)
    return clock, gate


def test_startup_waits_for_both_states_and_command_subscriptions():
    gate = ReadinessGate(Clock())
    gate.update_ready(False)
    assert gate.reason({'left': 1, 'right': 1})
    assert not gate.fault
    gate.update_ready(True)
    gate.update_state('left', [1] * 20)
    assert '右手' in gate.reason({'left': 1, 'right': 1})
    gate.update_state('right', [2] * 20)
    assert '订阅' in gate.reason({'left': 1, 'right': 0})
    assert gate.reason({'left': 1, 'right': 1}) == ''


def test_feedback_preserves_large_reserved_registers_and_ros_array(live_gate):
    _, gate = live_gate
    feedback = array('d', [255] * 20)
    for index in RESERVED_SLOTS:
        feedback[index] = 65535
    gate.update_state('right', feedback)
    assert gate.states['right'] == list(feedback)
    assert gate.states['left'] == [1] * 20
    assert gate.reason({'left': 1, 'right': 1}) == ''


def test_feedback_target_zeros_only_reserved_slots_without_mutating_raw_values():
    feedback = list(range(20))
    for index in RESERVED_SLOTS:
        feedback[index] = 65535
    target = feedback_target(feedback)
    assert all(target[index] == 0 for index in RESERVED_SLOTS)
    assert all(target[index] == feedback[index] for index in ACTIVE_SLOTS)
    assert all(feedback[index] == 65535 for index in RESERVED_SLOTS)


@pytest.mark.parametrize('index', ACTIVE_SLOTS)
def test_out_of_range_active_feedback_latches_both_hands_without_clipping(live_gate, index):
    _, gate = live_gate
    feedback = [100] * 20
    feedback[index] = 256
    with pytest.raises(ValueError, match='0–255'):
        feedback_target(feedback)
    gate.update_state('right', feedback)
    assert gate.states['right'][index] == 256
    assert '状态无效' in gate.reason({'left': 1, 'right': 1})
    gate.update_state('right', [100] * 20)
    assert gate.reason({'left': 1, 'right': 1}) == gate.fault


@pytest.mark.parametrize('values', [[], [0] * 19, [0] * 19 + [-1], [65536] * 20,
                                   [float('nan')] * 20, ['20'] * 20, [True] * 20])
def test_invalid_feedback_latches_without_replacing_last_good_sample(live_gate, values):
    _, gate = live_gate
    gate.update_state('left', values)
    assert '左手状态无效' in gate.fault
    assert gate.states['left'] == [1] * 20
    gate.update_state('left', [0] * 20)
    assert gate.reason({'left': 1, 'right': 1}) == gate.fault


def test_readiness_loss_remains_latched_after_recovery_messages(live_gate):
    _, gate = live_gate
    gate.update_ready(False)
    reason = gate.fault
    assert '失去就绪' in reason
    gate.update_ready(True)
    gate.update_state('left', [1] * 20)
    gate.update_state('right', [2] * 20)
    assert gate.reason({'left': 1, 'right': 1}) == reason


def test_single_stale_hand_disables_both_hands(live_gate):
    clock, gate = live_gate
    clock.now = 0.4
    gate.update_state('right', [3] * 20)
    clock.now = 0.501
    assert '左手状态超时' in gate.reason({'left': 1, 'right': 1})


def test_state_boundary_is_inclusive_and_next_sample_cannot_hide_timeout(live_gate):
    clock, gate = live_gate
    clock.now = 0.5
    assert gate.reason({'left': 1, 'right': 1}) == ''
    clock.now = 0.501
    gate.update_state('left', [3] * 20)
    gate.update_state('right', [4] * 20)
    assert '状态超时' in gate.reason({'left': 1, 'right': 1})


def test_readiness_timeout_is_not_masked_by_new_true_message():
    clock = Clock()
    gate = ReadinessGate(clock)
    gate.update_ready(True)
    for tick in range(1, 11):
        clock.now = tick / 4
        gate.update_state('left', [1] * 20)
        gate.update_state('right', [2] * 20)
    assert gate.reason({'left': 1, 'right': 1}) == ''
    clock.now = 2.501
    gate.update_ready(True)
    assert '心跳超时' in gate.reason({'left': 1, 'right': 1})


def test_startup_without_any_data_waits_instead_of_inventing_state():
    clock = Clock()
    gate = ReadinessGate(clock)
    clock.now = 100
    gate.update_ready(False)
    assert gate.states == {}
    assert gate.state_times == {}
    assert not gate.fault
    assert '等待' in gate.reason({'left': 1, 'right': 1})
