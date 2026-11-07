"""Turn passive piano-key joint motion into timestamped note edges."""

KEY_NOTES = range(21, 109)


def key_joint_name(note):
    return f"piano_key_{note:03d}_hinge"


class KeyEvents:
    """Read key angles in sim time using separate press and release thresholds."""

    def __init__(self, model, *, press_fraction=0.55, release_fraction=0.30):
        if not 0 < release_fraction < press_fraction < 1:
            raise ValueError("Key thresholds must satisfy 0 < release < press < 1")
        self._keys = []
        for note in KEY_NOTES:
            joint = model.joint(key_joint_name(note))
            limit = float(joint.range[1])
            self._keys.append((note, int(joint.qposadr[0]),
                               press_fraction * limit, release_fraction * limit))
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
