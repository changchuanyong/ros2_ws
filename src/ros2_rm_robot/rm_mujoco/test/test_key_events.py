"""Check the piano-key activation thresholds used by the flat-palm simulation."""

import math
from pathlib import Path
import sys

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.keyboard import (  # noqa: E402
    KEY_NOTES, ROBOPIANIST_ACTIVATION_DEG, KeyEvents, KeyHighlight, key_joint_name,
)

# The generated scene gives white keys asin(0.010 / 0.15) of travel and black keys
# asin(0.008 / 0.085).
WHITE_TRAVEL = math.asin(0.010 / 0.15)
BLACK_TRAVEL = math.asin(0.008 / 0.085)
WHITE_CLASSES = frozenset((0, 2, 4, 5, 7, 9, 11))


class _Joint:
    def __init__(self, index, limit):
        self.range = (0.0, limit)
        self.qposadr = [index]


class _Model:
    def __init__(self):
        self._joints = {
            key_joint_name(note): _Joint(index, WHITE_TRAVEL if note % 12 in WHITE_CLASSES
                                         else BLACK_TRAVEL)
            for index, note in enumerate(KEY_NOTES)
        }

    def joint(self, name):
        return self._joints[name]


class _Data:
    def __init__(self):
        self.qpos = [0.0] * len(KEY_NOTES)
        self.time = 0.0


def _thresholds(events, note):
    for entry, _, press, release in events._keys:
        if entry == note:
            return press, release
    raise AssertionError(f"missing key {note}")


def test_default_thresholds_stay_a_fraction_of_travel():
    events = KeyEvents(_Model())
    press, release = _thresholds(events, 72)
    assert press == pytest.approx(0.55 * WHITE_TRAVEL)
    assert release == pytest.approx(0.30 * WHITE_TRAVEL)


def test_degree_thresholds_match_the_robopianist_activation_test():
    events = KeyEvents(_Model(), press_deg=ROBOPIANIST_ACTIVATION_DEG, release_deg=1.0)
    press, release = _thresholds(events, 72)
    assert press == pytest.approx(WHITE_TRAVEL - math.radians(0.5))
    assert release == pytest.approx(WHITE_TRAVEL - math.radians(1.0))
    black_press, _ = _thresholds(events, 73)
    assert black_press == pytest.approx(BLACK_TRAVEL - math.radians(0.5))


def test_edges_need_both_thresholds_to_be_crossed():
    events = KeyEvents(_Model(), press_deg=0.5, release_deg=1.0)
    index = next(index for note, index, _, _ in events._keys if note == 72)
    press, release = _thresholds(events, 72)
    data = _Data()

    data.time, data.qpos[index] = 0.1, release + 1e-6
    assert events.update(data) == []
    data.time, data.qpos[index] = 0.2, press
    assert events.update(data) == [(0.2, "on", 72)]
    data.time, data.qpos[index] = 0.3, release + 1e-6
    assert events.update(data) == []
    data.time, data.qpos[index] = 0.4, release
    assert events.update(data) == [(0.4, "off", 72)]


@pytest.mark.parametrize("kwargs, message", [
    ({"press_deg": 0.5}, "both"),
    ({"press_deg": 1.0, "release_deg": 0.5}, "press_deg < release_deg"),
    ({"press_deg": 0.1, "release_deg": 10.0}, "travels"),
    ({"press_fraction": 0.3, "release_fraction": 0.5}, "0 < release < press < 1"),
])
def test_invalid_thresholds_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        KeyEvents(_Model(), **kwargs)


# A white key with its two geoms and one black key are enough to exercise the colours.
MINIMAL_KEYBOARD = """
<mujoco>
  <worldbody>
    <body name="keys">
      <geom name="piano_key_073" type="box" size="0.006 0.04 0.017"/>
      <geom name="piano_key_074" type="box" size="0.011 0.03 0.011"/>
      <geom name="piano_key_074_rear" type="box" size="0.004 0.04 0.011"/>
    </body>
  </worldbody>
</mujoco>
"""


def test_highlight_marks_pressed_keys_and_restores_the_rest():
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_string(MINIMAL_KEYBOARD)
    original = model.geom_rgba.copy()
    pressed = list(KeyHighlight.PRESSED)
    highlight = KeyHighlight(model)

    highlight.set_pressed([74])
    for name in ("piano_key_074", "piano_key_074_rear"):
        assert list(model.geom_rgba[model.geom(name).id]) == pytest.approx(pressed)
    black = model.geom("piano_key_073").id
    assert list(model.geom_rgba[black]) == pytest.approx(list(original[black]))

    highlight.set_pressed([])
    for name in ("piano_key_074", "piano_key_074_rear", "piano_key_073"):
        geom = model.geom(name).id
        assert list(model.geom_rgba[geom]) == pytest.approx(list(original[geom]))
