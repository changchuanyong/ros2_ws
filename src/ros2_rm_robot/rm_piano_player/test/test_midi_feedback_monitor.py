"""Exercise feedback startup with real ROS logging and a fake MIDI port."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

rclpy = pytest.importorskip("rclpy")
String = pytest.importorskip("std_msgs.msg").String

source = Path(__file__).resolve().parents[1] / "src" / "midi_feedback_monitor.py"
spec = importlib.util.spec_from_file_location("midi_feedback_monitor", source)
feedback_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feedback_module)


@pytest.fixture
def enabled_monitor(monkeypatch):
    # Keep ROS discovery local to this test process and outside the default domain.
    monkeypatch.setenv("ROS_LOCALHOST_ONLY", "1")
    midi_port = Mock(spec=["iter_pending", "close"])
    midi_port.iter_pending.return_value = ()
    fake_mido = ModuleType("mido")
    fake_mido.open_input = Mock(return_value=midi_port)
    monkeypatch.setitem(sys.modules, "mido", fake_mido)
    rclpy.init(
        args=[
            "--ros-args", "-p", "enabled:=true",
            "-p", "midi_input:=regression-test-input",
        ],
        domain_id=197,
    )
    monitor = None
    try:
        monitor = feedback_module.MidiFeedbackMonitor()
        yield monitor, fake_mido.open_input, midi_port
    finally:
        if monitor is not None:
            monitor.close()
            monitor.destroy_node()
        else:
            midi_port.close()
        rclpy.shutdown()


def test_enabled_startup_logs_and_opens_input(enabled_monitor):
    monitor, open_input, midi_port = enabled_monitor
    assert monitor.enabled
    assert monitor.input_port is midi_port
    open_input.assert_called_once_with("regression-test-input")


def test_invalid_expected_event_logs_without_stopping_monitor(enabled_monitor):
    monitor, _, _ = enabled_monitor
    monitor.expected_callback(String(data="{invalid json"))
    assert not monitor.expected
    assert not monitor.failed

    monitor.expected_callback(String(data='{"type":"on","note":60}'))
    assert len(monitor.expected[("on", 60)]) == 1
