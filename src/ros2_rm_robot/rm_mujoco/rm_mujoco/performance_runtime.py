"""Shared arm/hand trajectory sampling for simulation and calibration.

`run_performance.py` and the chord calibration both use these classes so a
short calibration replay and the final performance cannot silently disagree
about the 20-value hand transition or the arm waypoint timing.
"""

from bisect import bisect_right

import numpy as np

from .keyboard import KEY_NOTES, key_joint_name


KEY_LIMIT_TOLERANCE_RAD = 1e-9
# With the passive-key model at 2 ms, release from full legal travel and
# zero velocity reached -0.134500 deg on Jetson. Keep the press limit strict.
KEY_REBOUND_TOLERANCE_RAD = np.deg2rad(0.135)


def note_duration_tolerance(duration, edge_tolerance, timestep):
    return min(edge_tolerance, max(2 * timestep, 0.25 * duration))


class KeyTravelMonitor:
    """Record physical limit violations for all keys at every physics step."""

    def __init__(self, model):
        joints = [model.joint(key_joint_name(note)) for note in KEY_NOTES]
        self.addresses = np.array([int(joint.qposadr[0]) for joint in joints])
        self.bounds = np.array([joint.range for joint in joints])
        self.timestep = float(model.opt.timestep)
        self.maximum = np.full(len(joints), -np.inf)
        self.minimum = np.full(len(joints), np.inf)
        self.excess = np.zeros(len(joints))
        self.first_excess = np.full(len(joints), np.nan)
        self.excess_steps = np.zeros(len(joints), dtype=int)

    def observe(self, data):
        angles = data.qpos[self.addresses]
        np.maximum(self.maximum, angles, out=self.maximum)
        np.minimum(self.minimum, angles, out=self.minimum)
        lower = self.bounds[:, 0] - angles
        upper = angles - self.bounds[:, 1]
        excess = np.maximum(lower, upper)
        outside = (lower > KEY_REBOUND_TOLERANCE_RAD) | (upper > KEY_LIMIT_TOLERANCE_RAD)
        self.first_excess[outside & (self.excess_steps == 0)] = data.time
        self.excess_steps[outside] += 1
        np.maximum(self.excess, excess, out=self.excess, where=outside)
        return angles

    def violations(self):
        return [
            {"note": KEY_NOTES[index], "min_angle_deg": float(np.degrees(self.minimum[index])),
             "max_angle_deg": float(np.degrees(self.maximum[index])),
             "limit_deg": np.degrees(self.bounds[index]).tolist(),
             "max_excess_deg": float(np.degrees(self.excess[index])),
             "first_time_sec": float(self.first_excess[index]),
             "duration_sec": float(self.excess_steps[index] * self.timestep)}
            for index in np.flatnonzero(self.excess_steps)
        ]


def smoothstep(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


class ArmTrack:
    def __init__(self, start, waypoints):
        self.start = np.asarray(start, dtype=float)
        self.waypoints = sorted(waypoints, key=lambda item: item["time_sec"])

    def at(self, time_sec):
        previous = self.start
        for waypoint in self.waypoints:
            if waypoint["time_sec"] <= 0:
                previous = np.asarray(waypoint["joints"], dtype=float)
                continue
            if time_sec < waypoint["time_sec"]:
                begin = float(waypoint["move_after_sec"])
                if time_sec <= begin or waypoint["time_sec"] <= begin:
                    return previous
                return previous + smoothstep(
                    (time_sec - begin) / (waypoint["time_sec"] - begin)) * (
                        np.asarray(waypoint["joints"], dtype=float) - previous)
            previous = np.asarray(waypoint["joints"], dtype=float)
        return previous


class HandTrack:
    def __init__(self, ready, states, transition_sec):
        self.ready = np.asarray(ready, dtype=float)
        self.states = sorted(states, key=lambda item: item["time_sec"])
        self.transition = float(transition_sec)
        self.times = []
        self.segments = []
        for state in self.states:
            time = float(state["time_sec"])
            start = self.at(time)
            self.times.append(time)
            duration = float(state.get("transition_sec", self.transition))
            self.segments.append((start, np.asarray(state["positions"], dtype=float), duration))

    def at(self, time_sec):
        index = bisect_right(self.times, time_sec) - 1
        if index < 0:
            return self.ready
        start, target, duration = self.segments[index]
        if duration <= 0:
            return target
        weight = smoothstep((time_sec - self.times[index]) / duration)
        return start + weight * (target - start)
