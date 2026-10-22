"""Exercise GUI preflight and launch lifetime without opening hardware ports."""

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip('launch')
from launch import LaunchDescription, LaunchService  # noqa: E402
from launch.actions import ExecuteProcess, RegisterEventHandler, SetLaunchConfiguration  # noqa: E402
from launch.event_handlers import OnProcessStart  # noqa: E402

from rm_l20_driver import gui_launch  # noqa: E402


def launch_module():
    path = Path(__file__).resolve().parents[1] / 'launch' / 'l20_dual_rs485.launch.py'
    spec = importlib.util.spec_from_file_location('l20_gui_launch_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('enabled', [False, True])
def test_gui_is_optional_and_window_exit_stops_driver(monkeypatch, enabled):
    module = launch_module()
    monkeypatch.setattr(module, 'hand_arguments', lambda: [])
    started, preflight, captured = [], [], {}

    def driver(topic):
        captured['driver_topic'] = topic
        return ExecuteProcess(cmd=[sys.executable, '-c',
                                   'import time; time.sleep(30)' if enabled else 'pass'])

    def gui(**kwargs):
        captured['gui_topic'] = kwargs['parameters'][0]['ready_topic']
        return ExecuteProcess(cmd=[sys.executable, '-c', 'pass'], condition=kwargs['condition'])

    def check(context):
        preflight.append(True)
        return []

    monkeypatch.setattr(module, 'dual_hand_node', driver)
    monkeypatch.setattr(module, 'Node', gui)
    monkeypatch.setattr(module, 'check_gui_environment', check)
    description = module.generate_launch_description()
    processes = [action for action in description.entities if isinstance(action, ExecuteProcess)]
    handlers = [RegisterEventHandler(OnProcessStart(
        target_action=process, on_start=lambda event, context, index=index:
        started.append(index) or [])) for index, process in enumerate(processes)]
    service = LaunchService()
    service.include_launch_description(LaunchDescription([
        SetLaunchConfiguration('use_gui', str(enabled).lower()), *handlers, *description.entities]))
    service.run()
    assert 0 in started
    assert (1 in started) is enabled
    assert bool(preflight) is enabled
    assert captured['driver_topic'] == captured['gui_topic']
    previous = captured['driver_topic']
    module.generate_launch_description()
    assert captured['driver_topic'] != previous


def test_missing_gui_dependencies_have_actionable_error(monkeypatch):
    monkeypatch.setattr(gui_launch.importlib.util, 'find_spec', lambda name: None)
    with pytest.raises(RuntimeError, match='python3-pyqt5 python3-yaml'):
        gui_launch.check_gui_environment(None)


def test_no_display_reports_headless_option(monkeypatch):
    monkeypatch.setattr(gui_launch.importlib.util, 'find_spec', lambda name: object())
    for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'QT_QPA_PLATFORM'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match='use_gui:=false'):
        gui_launch.check_gui_environment(None)


@pytest.mark.parametrize('failure', ['plugin', 'timeout'])
def test_unusable_qt_display_reports_error_before_hardware(monkeypatch, failure):
    monkeypatch.setattr(gui_launch.importlib.util, 'find_spec', lambda name: object())
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')

    def run(*args, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(args[0], 10)
        return SimpleNamespace(returncode=-6, stderr='Qt platform plugin cannot connect')

    monkeypatch.setattr(gui_launch.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='L20 GUI'):
        gui_launch.check_gui_environment(None)


def test_preflight_failure_prevents_driver_process_start(monkeypatch):
    module = launch_module()
    monkeypatch.setattr(module, 'hand_arguments', lambda: [])
    monkeypatch.setattr(module, 'dual_hand_node', lambda topic:
                        ExecuteProcess(cmd=[sys.executable, '-c', 'pass']))
    monkeypatch.setattr(module, 'Node', lambda **kwargs:
                        ExecuteProcess(cmd=[sys.executable, '-c', 'pass']))

    def fail(context):
        raise RuntimeError('injected missing display')

    monkeypatch.setattr(module, 'check_gui_environment', fail)
    description = module.generate_launch_description()
    started = []
    service = LaunchService()
    service.include_launch_description(LaunchDescription([
        SetLaunchConfiguration('use_gui', 'true'),
        RegisterEventHandler(OnProcessStart(on_start=lambda event, context:
                                           started.append(event) or [])),
        *description.entities]))
    assert service.run() != 0
    assert not started
