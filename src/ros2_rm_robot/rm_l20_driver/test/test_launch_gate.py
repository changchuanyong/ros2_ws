"""Run the actual launch event gate with harmless local Python processes."""

import sys
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip('launch')
from launch import LaunchDescription, LaunchService  # noqa: E402
from launch.actions import ExecuteProcess, OpaqueFunction, RegisterEventHandler  # noqa: E402
from launch.event_handlers import OnProcessExit  # noqa: E402

from rm_l20_driver.launch_support import hand_exit, readiness_exit  # noqa: E402
from rm_l20_driver import launch_support  # noqa: E402


@pytest.mark.parametrize('exit_code,should_start', [(0, True), (1, False), (2, False)])
def test_readiness_process_gates_hardware_actions(exit_code, should_start):
    released = []
    process = ExecuteProcess(cmd=[sys.executable, '-c', f'raise SystemExit({exit_code})'])

    def record(context):
        released.append('hardware')
        return []

    description = LaunchDescription([
        RegisterEventHandler(OnProcessExit(
            target_action=process, on_exit=readiness_exit([OpaqueFunction(function=record)]))),
        process,
    ])
    service = LaunchService()
    service.include_launch_description(description)
    service.run()
    assert bool(released) == should_start


def test_driver_exit_prevents_delayed_ready_from_starting_hardware():
    released = []
    hands = ExecuteProcess(cmd=[sys.executable, '-c', 'raise SystemExit(1)'])
    waiter = ExecuteProcess(cmd=[sys.executable, '-c', 'import time; time.sleep(2)'])

    def record(context):
        released.append('hardware')
        return []

    service = LaunchService()
    service.include_launch_description(LaunchDescription([
        RegisterEventHandler(OnProcessExit(target_action=hands, on_exit=hand_exit)),
        RegisterEventHandler(OnProcessExit(
            target_action=waiter, on_exit=readiness_exit([OpaqueFunction(function=record)]))),
        hands, waiter,
    ]))
    service.run()
    assert released == []


def test_actual_piano_entry_has_only_hands_and_waiter_at_start(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    path = root / 'rm_piano_player' / 'launch' / 'rm_75_dual_l20_piano_real.launch.py'
    spec = importlib.util.spec_from_file_location('piano_real_launch_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'get_package_share_directory', lambda name: str(root / name))
    monkeypatch.setattr(launch_support, 'get_package_share_directory', lambda name: str(root / name))
    description = module.generate_launch_description()
    # No arms, MIDI process, or delayed player may be a top-level startup action.
    processes = [action for action in description.entities if isinstance(action, ExecuteProcess)]
    executables = [node.node_executable for node in processes]
    assert executables == ['l20_dual_rs485_driver', 'l20_wait_ready']
    from launch.actions import IncludeLaunchDescription, TimerAction
    assert not any(isinstance(action, (IncludeLaunchDescription, TimerAction))
                   for action in description.entities)


def test_each_startup_waiter_is_isolated_from_other_runs(monkeypatch):
    monkeypatch.setattr(launch_support, 'Node', lambda **kwargs: kwargs)
    first_driver, first_waiter = launch_support.gated_hand_nodes()
    second_driver, second_waiter = launch_support.gated_hand_nodes()
    first = first_driver['remappings'][0][1]
    second = second_driver['remappings'][0][1]
    assert first != second
    assert first_waiter['remappings'] == [('/l20/hands_ready', first)]
    assert second_waiter['remappings'] == [('/l20/hands_ready', second)]
