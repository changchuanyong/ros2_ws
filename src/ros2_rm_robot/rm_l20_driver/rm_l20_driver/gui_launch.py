"""Validate an optional GUI before starting either serial connection."""

import importlib.util
import os
import subprocess
import sys

from launch.actions import EmitEvent
from launch.events import Shutdown


def check_gui_environment(context):
    """Probe Qt in a child process; headless launches never call this function."""
    missing = [name for name in ('PyQt5', 'yaml')
               if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(
            'L20 GUI 缺少依赖: ' + ', '.join(missing) +
            '。请安装 python3-pyqt5 python3-yaml，或使用 use_gui:=false。')
    if (not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY') and
            os.environ.get('QT_QPA_PLATFORM') not in ('offscreen', 'minimal')):
        raise RuntimeError(
            'L20 GUI 没有可用桌面环境，请在桌面终端启动，或使用 use_gui:=false。')
    try:
        result = subprocess.run(
            [sys.executable, '-c',
             'from PyQt5.QtWidgets import QApplication; app = QApplication([])'],
            capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f'L20 GUI 无法初始化显示环境: {error}') from error
    if result.returncode != 0:
        raise RuntimeError(
            'L20 GUI 无法初始化 Qt 显示环境，请检查桌面权限和 Qt 插件，'
            '或使用 use_gui:=false。\n' + result.stderr[-2000:])
    return []


def gui_exit(event, context):
    """Closing the window also releases the driver-owned serial connections."""
    if context.is_shutdown:
        return []
    return [EmitEvent(event=Shutdown(reason=f'L20 GUI exited: {event.returncode}'))]
