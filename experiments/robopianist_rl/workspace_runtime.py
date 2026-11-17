"""Resolve the bundled RoboPianist when invoked directly from ros2_ws."""

from pathlib import Path
import sys


def use_workspace_robopianist():
    root = Path(__file__).resolve().parents[2] / "third_party" / "robopianist"
    if (root / "robopianist" / "__init__.py").is_file():
        sys.path.insert(0, str(root))
