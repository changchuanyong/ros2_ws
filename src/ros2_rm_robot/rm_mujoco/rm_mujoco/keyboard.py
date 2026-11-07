"""Turn passive piano-key joint motion into timestamped note edges."""

import math

KEY_NOTES = range(21, 109)

# Distance from full travel, in degrees, used by the RoboPianist activation test.
ROBOPIANIST_ACTIVATION_DEG = 0.5


def key_joint_name(note):
    return f"piano_key_{note:03d}_hinge"


def key_site_name(note):
    return f"piano_key_{note:03d}_site"


def key_geom_names(note):
    """Geoms of one key body; white keys are split into a front and rear section."""
    return (f"piano_key_{note:03d}", f"piano_key_{note:03d}_rear")


class KeyEvents:
    """Read key angles in sim time using separate press and release thresholds.

    Thresholds are either a fraction of the key travel or, when `press_deg` and
    `release_deg` are given, an absolute distance below full travel in degrees.
    The degree form matches RoboPianist's `activation` test, which counts a key as
    pressed while it is within 0.5 degrees of the end of its range.
    """

    def __init__(self, model, *, press_fraction=0.55, release_fraction=0.30,
                 press_deg=None, release_deg=None):
        if press_deg is None and release_deg is None:
            if not 0 < release_fraction < press_fraction < 1:
                raise ValueError("Key thresholds must satisfy 0 < release < press < 1")
        elif press_deg is None or release_deg is None:
            raise ValueError("Specify both press_deg and release_deg, or neither")
        elif not 0 <= press_deg < release_deg:
            raise ValueError("Key thresholds must satisfy 0 <= press_deg < release_deg")
        self._keys = []
        for note in KEY_NOTES:
            joint = model.joint(key_joint_name(note))
            limit = float(joint.range[1])
            if press_deg is None:
                press, release = press_fraction * limit, release_fraction * limit
            else:
                if math.radians(release_deg) >= limit:
                    raise ValueError(
                        f"Key {note} travels {math.degrees(limit):.2f} deg, "
                        f"which is not longer than release_deg={release_deg}")
                press = limit - math.radians(press_deg)
                release = limit - math.radians(release_deg)
            self._keys.append((note, int(joint.qposadr[0]), press, release))
        self._active = set()

    def update(self, data):
        """Return (simulation time, 'on'/'off', MIDI note) edges for this step."""
        events = []
        for note, index, press, release in self._keys:
            angle = data.qpos[index]
            if note not in self._active and angle >= press:
                self._active.add(note)
                events.append((data.time, "on", note))
            elif note in self._active and angle <= release:
                self._active.remove(note)
                events.append((data.time, "off", note))
        return events


class KeyHighlight:
    """Recolour pressed keys like RoboPianist, without its grey-restore hack.

    RoboPianist writes (0.5, 0.5, 0.5, 1) back so the material shows through again.
    Here the compiled colours are snapshotted once and restored exactly.
    """

    PRESSED = (0.20, 0.80, 0.20, 1.0)

    def __init__(self, model):
        self._model = model
        self._ids = {}
        for note in KEY_NOTES:
            ids = []
            for name in key_geom_names(note):
                try:
                    ids.append(model.geom(name).id)
                except KeyError:
                    pass
            self._ids[note] = ids
        self._original = model.geom_rgba.copy()

    def set_pressed(self, notes):
        """Colour `notes` green and restore every other key to its compiled colour."""
        pressed = set(notes)
        for note, ids in self._ids.items():
            if ids:
                rgba = self.PRESSED if note in pressed else self._original[ids]
                self._model.geom_rgba[ids] = rgba
        return self
