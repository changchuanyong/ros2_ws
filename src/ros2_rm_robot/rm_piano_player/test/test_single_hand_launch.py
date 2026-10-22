"""Check launch selection and calibration gates without starting processes."""

import importlib.util
from pathlib import Path

import pytest
import yaml

pytest.importorskip('launch')
pytest.importorskip('rclpy')
from launch import LaunchContext  # noqa: E402
from launch.actions import IncludeLaunchDescription  # noqa: E402

from rm_piano_player import single_hand_launch as entry  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'rm_piano_player'
POSES = ('READY', 'PRESS_C', 'PRESS_D', 'PRESS_E', 'PRESS_F', 'PRESS_G')


@pytest.fixture
def configured_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(entry, 'get_package_share_directory', lambda name: str(ROOT / name))
    config = tmp_path / 'calibrated_test_poses.yaml'
    config.write_text(yaml.safe_dump({'poses': {
        name: {'positions': [float(index + 10)] * 20, 'verified': True}
        for index, name in enumerate(POSES)
    }}))
    created = []
    original_node = entry.Node

    def record_node(**kwargs):
        created.append(kwargs)
        return original_node(**kwargs)

    monkeypatch.setattr(entry, 'Node', record_node)

    def invoke(**overrides):
        context = LaunchContext()
        context.launch_configurations.update({
            'execute': 'false', 'mode': 'pose_test', 'pose': 'READY',
            'pose_config': str(config), 'hand_port': 'auto',
            'press_duration': '0.5', 'release_duration': '0.5', 'ready_settle': '1.0',
            'hand_identity_config': str(ROOT / 'rm_l20_driver' / 'config' / 'hand_identity.yaml'),
        })
        context.launch_configurations.update(overrides)
        return entry.launch_actions(context)

    return invoke, created, config


def test_dry_run_only_creates_player_with_empty_template_and_no_identity_access(configured_launch):
    invoke, created, _ = configured_launch
    invoke(pose_config=str(PACKAGE / 'config' / 'right_hand_ode_to_joy.yaml'),
           hand_identity_config='/does/not/exist.yaml', hand_port='/does/not/exist')
    assert [(node['package'], node['executable']) for node in created] == [
        ('rm_piano_player', 'l20_right_hand_piano.py')]
    assert created[0]['parameters'][0]['execute'] is False
    assert 'driver_node' not in created[0]['parameters'][0]


def test_execution_creates_only_right_driver_and_player_using_configured_uid(configured_launch):
    invoke, created, _ = configured_launch
    invoke(execute='true', mode='melody', hand_port='/dev/test_right_hand')
    assert [(node['package'], node['executable']) for node in created] == [
        ('rm_l20_driver', 'l20_rs485_driver'), ('rm_piano_player', 'l20_right_hand_piano.py')]
    driver, player = created
    identity_path = ROOT / 'rm_l20_driver' / 'config' / 'hand_identity.yaml'
    expected_uid = yaml.safe_load(identity_path.read_text())[
        'l20_dual_rs485_driver']['ros__parameters']['right_hand_uid']
    assert driver['parameters'][0] == {
        'hand_type': 'right', 'hand_joint': 'L20-11', 'modbus': '/dev/test_right_hand',
        'expected_uid': expected_uid,
    }
    assert player['parameters'][0]['execute'] is True
    assert driver['name'] == player['parameters'][0]['driver_node']


def test_each_invocation_gets_separate_readiness_and_fault_channels(configured_launch):
    invoke, created, _ = configured_launch
    invoke(execute='true')
    invoke(execute='true')
    first_driver, first_player, second_driver, second_player = created
    first = first_player['parameters'][0]
    second = second_player['parameters'][0]
    assert first['driver_node'] != second['driver_node']
    assert first['ready_topic'] != second['ready_topic']
    assert first['fault_topic'] != second['fault_topic']
    assert first['written_topic'] != second['written_topic']
    for driver, parameters in ((first_driver, first), (second_driver, second)):
        assert dict(driver['remappings']) == {
            '~/ready': parameters['ready_topic'],
            '/robopianist/feedback_abort': parameters['fault_topic'],
            '~/command_written': parameters['written_topic'],
        }


@pytest.mark.parametrize('override', [
    {'execute': 'yes'}, {'mode': 'unknown'}, {'pose': 'PRESS_A'},
    {'press_duration': '0'}, {'release_duration': '-1'}, {'ready_settle': 'nan'},
])
def test_invalid_options_create_no_processes(configured_launch, override):
    invoke, created, _ = configured_launch
    with pytest.raises(ValueError):
        invoke(**override)
    assert created == []


def test_empty_pose_template_refuses_execution_before_driver_creation(configured_launch):
    invoke, created, _ = configured_launch
    with pytest.raises(ValueError, match='READY'):
        invoke(execute='true', pose_config=str(PACKAGE / 'config' / 'right_hand_ode_to_joy.yaml'))
    assert created == []


def test_unverified_melody_refuses_execution_before_driver_creation(configured_launch):
    invoke, created, config = configured_launch
    data = yaml.safe_load(config.read_text())
    data['poses']['PRESS_E']['verified'] = False
    config.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match='PRESS_E'):
        invoke(execute='true', mode='melody')
    assert created == []


def test_launch_entry_contains_no_arm_moveit_midi_or_included_launch(monkeypatch):
    monkeypatch.setattr(entry, 'get_package_share_directory', lambda name: str(ROOT / name))
    path = PACKAGE / 'launch' / 'l20_right_hand_piano.launch.py'
    spec = importlib.util.spec_from_file_location('test_l20_right_entry', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    description = module.generate_launch_description()
    assert not any(isinstance(action, IncludeLaunchDescription) for action in description.entities)
