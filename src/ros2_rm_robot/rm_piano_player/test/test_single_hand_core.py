"""Exercise calibration refusal, release timing, and terminal playback states."""

import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_piano_player.single_hand_core import (  # noqa: E402
    MELODY, POSE_NAMES, Playback, calibration_report, load_pose_config,
    validate_execution,
)


def calibration(verified=True):
    return {'poses': {
        name: {'positions': [float(index)] * 20, 'verified': verified}
        for index, name in enumerate(POSE_NAMES)
    }}


def playback(**kwargs):
    return Playback(validate_execution(calibration(), 'melody'), **kwargs)


@pytest.mark.parametrize('value', [None, {}, {'poses': None}, {'poses': []}])
def test_invalid_document_reports_every_missing_pose(value):
    report = calibration_report(value)
    assert tuple(report) == POSE_NAMES
    assert all(not entry['valid'] for entry in report.values())


def test_empty_template_does_not_become_an_executable_zero_pose(tmp_path):
    path = tmp_path / 'poses.yaml'
    path.write_text('poses:\n  READY:\n    positions: []\n    verified: false\n')
    config = load_pose_config(path)
    assert not calibration_report(config)['READY']['valid']
    with pytest.raises(ValueError, match='exactly 20'):
        validate_execution(config)


@pytest.mark.parametrize('document', ['', '[]', 'poses: []', 'poses: null', 'name: example'])
def test_load_rejects_missing_pose_mapping(tmp_path, document):
    path = tmp_path / 'poses.yaml'
    path.write_text(document)
    with pytest.raises(ValueError, match='poses mapping'):
        load_pose_config(path)


@pytest.mark.parametrize('positions', [
    [], [0] * 19, [0] * 21, '0' * 20,
    [0] * 19 + [-1], [0] * 19 + [256], [0] * 19 + [float('nan')],
    [0] * 19 + [float('inf')], [0] * 19 + [float('-inf')],
    [0] * 19 + [10**400], [0] * 19 + [True], [0] * 19 + ['123'],
    [0] * 19 + [None],
])
def test_reject_invalid_positions_without_clipping(positions):
    config = calibration()
    config['poses']['READY']['positions'] = positions
    with pytest.raises(ValueError, match='READY:'):
        validate_execution(config)


def test_numeric_boundaries_and_input_immutability():
    config = calibration()
    config['poses']['READY']['positions'] = [0, 255, 12.5, 0] * 5
    before = copy.deepcopy(config)
    result = validate_execution(config)
    assert result['READY'] == [0.0, 255.0, 12.5, 0.0] * 5
    result['READY'][0] = 99.0
    assert config == before


def test_pose_test_accepts_unverified_selected_poses_only():
    config = calibration(False)
    del config['poses']['PRESS_G']
    assert set(validate_execution(config, 'pose_test', 'PRESS_C')) == {'READY', 'PRESS_C'}
    with pytest.raises(ValueError, match='PRESS_G'):
        validate_execution(config, 'pose_test', 'PRESS_G')


@pytest.mark.parametrize('name', POSE_NAMES)
def test_melody_requires_every_pose_verified(name):
    config = calibration()
    config['poses'][name]['verified'] = False
    with pytest.raises(ValueError, match=f'{name}: not verified'):
        validate_execution(config, 'melody')


@pytest.mark.parametrize('verified', [None, 1, 'true', 'false'])
def test_verification_flag_must_be_boolean(verified):
    config = calibration()
    config['poses']['READY']['verified'] = verified
    with pytest.raises(ValueError, match='verified must be true or false'):
        validate_execution(config)


@pytest.mark.parametrize(('mode', 'pose'), [('other', 'READY'), ('pose_test', 'C')])
def test_unknown_mode_and_pose_rejected(mode, pose):
    with pytest.raises(ValueError):
        validate_execution(calibration(), mode, pose)


@pytest.mark.parametrize('parameter', ['press_duration', 'release_duration', 'ready_settle'])
@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), '1', True])
def test_invalid_duration_rejected(parameter, value):
    with pytest.raises(ValueError, match=parameter):
        playback(**{parameter: value})


def test_ready_only_sends_one_command():
    player = playback()
    assert player.start(10) == [
        {'pose': 'READY', 'note_index': 0, 'note': None, 'sent_at': 10}]
    assert player.start(10.1) == []
    assert player.tick(10.99) == []
    assert player.tick(11) == []
    assert player.done and player.status['phase'] == 'completed'
    assert player.tick(100) == []


def test_press_test_runs_ready_press_ready_once():
    player = playback(pose='PRESS_C')
    commands = player.start(0) + player.tick(1) + player.tick(1.5)
    assert [command['pose'] for command in commands] == ['READY', 'PRESS_C', 'READY']
    assert commands[1]['note'] == 60
    assert player.tick(1.99) == [] and not player.done
    assert player.tick(2) == [] and player.done


def test_melody_has_exact_fifteen_notes_and_releases_every_press():
    player = playback(mode='melody')
    commands = player.start(0)
    now = 1.0
    while not player.done:
        commands.extend(player.tick(now))
        now += 0.5
    assert MELODY == ('E', 'E', 'F', 'G', 'G', 'F', 'E', 'D', 'C', 'C', 'D', 'E', 'E', 'D', 'D')
    assert len(commands) == 31
    assert [item['pose'][-1] for item in commands[1::2]] == list(MELODY)
    assert [item['note'] for item in commands[1::2]] == [
        64, 64, 65, 67, 67, 65, 64, 62, 60, 60, 62, 64, 64, 62, 62]
    assert [item['note_index'] for item in commands[1::2]] == list(range(1, 16))
    assert all(item['pose'] == 'READY' for item in commands[2::2])
    for previous, current in zip(commands, commands[1:]):
        assert current['sent_at'] - previous['sent_at'] >= 0.5


def test_delayed_tick_does_not_catch_up_or_compress_repeated_note_release():
    player = playback(mode='melody')
    player.start(0)
    assert player.tick(10)[0]['pose'] == 'PRESS_E'
    assert player.tick(10.1) == []
    assert player.tick(20)[0]['pose'] == 'READY'
    assert player.tick(20) == []
    assert player.tick(20.499) == []
    command = player.tick(20.5)[0]
    assert command['pose'] == 'PRESS_E' and command['note_index'] == 2


@pytest.mark.parametrize('at_press', [False, True])
def test_stop_sends_at_most_one_ready_and_no_later_notes(at_press):
    player = playback(mode='melody')
    player.start(0)
    if at_press:
        player.tick(1)
    commands = player.stop(1.1)
    assert [command['pose'] for command in commands] == (['READY'] if at_press else [])
    assert player.status['phase'] == 'stopped'
    assert player.stop(2) == player.tick(10) == player.start(20) == []


def test_stop_before_start_does_not_command_a_pose():
    player = playback(mode='melody')
    assert player.stop(0) == []
    assert player.start(1) == []


def test_stop_with_unhealthy_connection_does_not_release():
    player = playback(mode='melody')
    player.start(0)
    player.tick(1)
    assert player.stop(1.1, healthy=False) == []
    assert player.tick(100) == []


@pytest.mark.parametrize('phase', ['idle', 'settling', 'pressing', 'releasing'])
def test_failure_latches_and_never_sends_a_recovery_pose(phase):
    player = playback(mode='melody')
    if phase != 'idle':
        player.start(0)
    if phase in ('pressing', 'releasing'):
        player.tick(1)
    if phase == 'releasing':
        player.tick(1.5)
    assert player.fail('state stale') == []
    assert player.done and player.status['reason'] == 'state stale'
    assert player.stop(2) == player.tick(100) == player.start(101) == []


def test_non_monotonic_time_is_rejected():
    player = playback(mode='melody')
    player.start(10)
    with pytest.raises(ValueError, match='backwards'):
        player.tick(9)
