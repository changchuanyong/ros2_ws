"""MuJoCo hand kinematics, candidate reachability and a small beam search.

This module is deliberately simulation-only.  It uses the passive-key MuJoCo
model, the calibrated right-hand READY/PRESS poses and a damped least-squares
arm IK to decide which finger can play each note.  The output is the
`piano_performance/1` plan played by `run_performance.py`; no MoveIt, real
controller or RS485 code is involved.
"""

from dataclasses import dataclass, field
import itertools
import math
from pathlib import Path
import re
import tempfile
import time

import mujoco as m
import numpy as np
import yaml

from .keyboard import KEY_NOTES, KeyEvents, key_joint_name
from .l20_joint_mapping import HAND_JOINT_SUFFIXES, command_positions
from .performance import FINGERS, MAX_CHORD, events_by_hand, group_events, validate_physical_key_spans
from .performance_runtime import ArmTrack, HandTrack, KeyTravelMonitor, note_duration_tolerance
from .scene import build_model, key_positions, load_layout

POSE_FINGER = {"C": "thumb", "D": "index", "E": "middle", "F": "ring", "G": "little"}
REFERENCE_PITCH = {"thumb": 60, "index": 62, "middle": 64, "ring": 65, "little": 67}
# Calibrated flat-palm wrist orientation used by the existing flat-palm demo.
PLAY_R = np.array([[0.0, -1.0, 0.0], [0.0, 0.0, 1.0], [-1.0, 0.0, 0.0]])
# The verified six-note simulation used 1.985 rad/s peak waypoint speed.
# At hand command start, its 20 ms tracking reached 0.0402 rad and 0.327 rad/s.
SIM_ARM_SPEED = 2.0
SIM_ARM_SETTLE_ERROR = 0.041
SIM_ARM_SETTLE_SPEED = 0.35
# Piano posture preferences.  These are soft costs, not hard joint targets:
# a pianist keeps the upper arm sloping down from the shoulder, the elbow clear
# of the torso and slightly behind the keys, and every joint away from its stop.
POSTURE_ELBOW_DROP_M = 0.10
POSTURE_ELBOW_LATERAL_M = -0.10
POSTURE_ELBOW_BACK_M = -0.34
POSTURE_ELBOW_BACK_TOL_M = 0.08
POSTURE_JOINT_MARGIN_RAD = 0.25
POSTURE_MIN_JOINT_MARGIN_RAD = 0.03
POSTURE_TABLE_CLEARANCE_M = 0.03
POSTURE_WEIGHTS = {
    "elbow_drop": 6.0,
    "elbow_lateral": 2.0,
    "elbow_back": 1.0,
    "joint_margin": 6.0,
    "table_clearance": 8.0,
}
# The first pass tries to keep every non-target finger off the keys.  The
# relaxed pass allows light extra finger/key contacts, which the simulation
# then checks against the actual key edges.
STRICT_ORIENTATIONS = (
    (0, 0, 0),
    (-10, 0, 0),
    (10, 0, 0),
    (0, -6, 0),
    (0, 6, 0),
    (0, 0, -6),
    (0, 0, 6),
    (-10, -6, 0),
    (10, -6, 0),
    (-20, 0, 0),
    (20, 0, 0),
)
RELAX_ORIENTATIONS = (
    (0, 0, 0),
    (-10, 0, 0),
    (10, 0, 0),
    (0, -6, 0),
    (0, 6, 0),
    (0, 0, -6),
    (0, 0, 6),
    (-10, -6, 0),
    (10, -6, 0),
)
# (dx, dy) relative to the key press point.  -0.038 m is the front part of a
# white key, which was the clean middle-finger contact found in calibration.
STRICT_OFFSETS = (
    (0.0, 0.0),
    (0.0, -0.038),
    (0.0, -0.020),
    (0.0, 0.018),
    (-0.006, 0.0),
    (0.006, 0.0),
)
RELAX_OFFSETS = (
    (0.0, 0.0),
    (0.0, -0.038),
)
CHORD_STRICT_OFFSETS = (
    (0.0, 0.0),
    (0.0, -0.038),
)
# The E4+G4 dyad required a rolled wrist; the C4+D4 dyad required yaw/roll/
# pitch together.  These extra orientations are only used for chords.
CHORD_STRICT_ORIENTATIONS = STRICT_ORIENTATIONS + (
    (0, -12, 0),
    (0, 12, 0),
    (-10, -12, -12),
    (-10, -12, 0),
    (10, -12, 0),
    (0, -12, -12),
    (0, 12, 12),
    (-20, -12, 0),
    (20, -12, 0),
)
CHORD_RELAX_ORIENTATIONS = RELAX_ORIENTATIONS + (
    (0, -12, 0),
    (0, 12, 0),
    (-10, -12, -12),
    (-10, -12, 0),
    (10, -12, 0),
    (0, -12, -12),
)


def rotate(axis, degrees):
    theta = math.radians(degrees)
    a, b = math.cos(theta), math.sin(theta)
    if axis == "z":
        return np.array([[a, -b, 0], [b, a, 0], [0, 0, 1]], dtype=float)
    if axis == "x":
        return np.array([[1, 0, 0], [0, a, -b], [0, b, a]], dtype=float)
    return np.array([[a, 0, b], [0, 1, 0], [-b, 0, a]], dtype=float)


def orientation_rotation(orientation, base):
    yaw, roll, pitch = orientation
    return rotate("z", yaw) @ rotate("y", pitch) @ rotate("x", roll) @ base


@dataclass
class Candidate:
    arm_q: np.ndarray
    hand20: list
    orientation: tuple
    cost: float
    detail: dict = field(default_factory=dict)
    hover_arm: np.ndarray = None
    posture: dict = field(default_factory=dict)


class PianoHandModel:
    """Build the passive-key model and expose the reachability oracle."""

    def __init__(self, package, scene_config, pose_file, press_depth=0.008,
                 chord_epsilon=1e-3):
        self.package = Path(package)
        self.press_depth = float(press_depth)
        self.chord_epsilon = float(chord_epsilon)
        self.hand_transition = 0.04
        self.scene_config = str(scene_config)
        self.layout = load_layout(scene_config)
        self.tmp = tempfile.TemporaryDirectory(prefix="piano_plan_")
        model_path = build_model(
            self.package / "models/rm_75_6fb_v_dual_l20.xml",
            self.layout, self.tmp.name, movable_keys=True)
        self.model = m.MjModel.from_xml_path(str(model_path))
        self.work = m.MjData(self.model)
        self.key_id = self.model.key("piano_ready").id
        m.mj_resetDataKeyframe(self.model, self.work, self.key_id)
        m.mj_forward(self.model, self.work)
        self.ready_q = self.work.qpos.copy()
        self.ready_ctrl = self.work.ctrl.copy()
        self.geom_names = [
            self.model.geom(i).name or self.model.body(self.model.geom_bodyid[i]).name
            for i in range(self.model.ngeom)]
        self.key_re = re.compile(r"^piano_key_(\d+)(?:_rear)?$")
        self.points = (np.asarray(key_positions(self.layout), dtype=float)
                       + np.asarray(self.layout["piano_frame"]["position"], dtype=float))
        self.key_qpos = {
            note: int(self.model.joint(key_joint_name(note)).qposadr[0])
            for note in KEY_NOTES}
        self.key_limit = {
            note: float(self.model.joint(key_joint_name(note)).range[1])
            for note in KEY_NOTES}
        self.sides = ("left", "right")
        self.arm_qpos = {}
        self.arm_dof = {}
        self.arm_act = {}
        self.arm_limits = {}
        self.hand_qpos = {}
        self.hand_act = {}
        self.wrist_id = {}
        self.ready_arm_q = {}
        self.ready_wrist_R = {}
        for side in self.sides:
            arm_joints = [self.model.joint(f"{side}_joint{i}") for i in range(1, 8)]
            self.arm_qpos[side] = np.array([int(joint.qposadr[0]) for joint in arm_joints])
            self.arm_dof[side] = np.array([int(joint.dofadr[0]) for joint in arm_joints])
            self.arm_act[side] = np.array([
                int(np.flatnonzero(self.model.actuator_trnid[:, 0] == joint.id)[0])
                for joint in arm_joints])
            self.arm_limits[side] = np.array([
                [float(joint.range[0]), float(joint.range[1])] for joint in arm_joints])
            hand_joints = [self.model.joint(f"{side}_{suffix}") for suffix in HAND_JOINT_SUFFIXES]
            self.hand_qpos[side] = np.array([int(joint.qposadr[0]) for joint in hand_joints])
            self.hand_act[side] = np.array([
                int(np.flatnonzero(self.model.actuator_trnid[:, 0] == joint.id)[0])
                for joint in hand_joints])
            self.wrist_id[side] = self.model.body(f"{side}_l20_base_link").id
            self.ready_arm_q[side] = self.ready_q[self.arm_qpos[side]].copy()
            m.mj_kinematics(self.model, self.work)
            self.ready_wrist_R[side] = self.work.xmat[self.wrist_id[side]].reshape(3, 3).copy()
        self.play_R = PLAY_R.copy()
        self.strict_orientations = STRICT_ORIENTATIONS
        self.relax_orientations = RELAX_ORIENTATIONS
        self.strict_offsets = STRICT_OFFSETS
        self.relax_offsets = RELAX_OFFSETS
        self.chord_strict_orientations = CHORD_STRICT_ORIENTATIONS
        self.chord_relax_orientations = CHORD_RELAX_ORIENTATIONS
        self.chord_strict_offsets = CHORD_STRICT_OFFSETS
        self.baseline = self._contact_set()
        self.table_top = (float(self.layout["table"]["position"][2])
                          + 0.5 * float(self.layout["table"]["size"][2]))
        self.key_top = float(self.layout["piano_frame"]["position"][2])
        self.arm_body = {
            side: {
                name: self.model.body(f"{side}_{name}").id
                for name in ("Link1", "Link3", "Link5", "l20_base_link")}
            for side in self.sides}
        self.posture_data = m.MjData(self.model)
        self.jp = np.zeros((3, self.model.nv))
        self.jr = np.zeros_like(self.jp)
        self.fingertip = {}
        for side in self.sides:
            for finger in FINGERS:
                mesh = self.model.mesh(
                    f"l20_{finger}_link{5 if finger == 'thumb' else 4}")
                gid = next(
                    i for i in range(self.model.ngeom)
                    if self.model.geom_type[i] == m.mjtGeom.mjGEOM_MESH
                    and self.model.geom_dataid[i] == mesh.id
                    and self.geom_names[i].startswith(side + "_"))
                verts = self.model.mesh_vert[
                    mesh.vertadr[0]:mesh.vertadr[0] + mesh.vertnum[0]].copy()
                self.fingertip[(side, finger)] = (gid, verts)
        self.tip_cfg = {}
        document = yaml.safe_load(Path(pose_file).read_text(encoding="utf-8"))
        poses = document["poses"]
        self.chord_overrides = {}
        self.chord_transitions = {}
        self.chord_arm_seeds = {}
        self.chord_release_poses = {}
        for key, values in (document.get("chords") or {}).items():
            if not isinstance(key, str) or not key:
                raise ValueError("chord override keys must be finger names joined by +")
            if isinstance(values, dict):
                seconds = float(values.get("transition_sec", 0.04))
                seed = np.asarray(values.get("arm_seed_rad", []), dtype=float)
                if (not math.isfinite(seconds) or seconds <= 0
                        or seed.shape not in ((0,), (7,)) or not np.all(np.isfinite(seed))):
                    raise ValueError(f"invalid calibration for chord {key!r}")
                self.chord_transitions[key] = seconds
                if seed.size:
                    self.chord_arm_seeds[key] = seed
                for finger, pose in (values.get("release_positions") or {}).items():
                    pose = np.asarray(pose, dtype=float)
                    if finger not in key.split("+") or pose.shape != (20,):
                        raise ValueError(f"invalid remaining {finger} pose for chord {key!r}")
                    self.chord_release_poses[key, finger] = np.clip(pose, 0.0, 255.0).tolist()
                values = values.get("positions")
            values = np.asarray(values, dtype=float)
            if values.shape != (20,):
                raise ValueError(f"chord override {key!r} must contain 20 values")
            self.chord_overrides[key] = values
        self.note_overrides = {}
        self.note_contacts = {}
        self.note_timing = {}
        self.short_note_poses = {}
        self.note_alternatives = {}
        for key, values in (document.get("notes") or {}).items():
            pitch, _, selected_finger = str(key).partition(":")
            try:
                note = int(pitch)
            except (TypeError, ValueError) as error:
                raise ValueError("note override keys must identify a MIDI note") from error
            finger = None
            if isinstance(values, dict):
                finger = values.get("finger", selected_finger)
                if finger not in FINGERS or selected_finger not in ("", finger):
                    raise ValueError(f"note override {note} requires a valid finger")
                alternatives = []
                for pose in values.get("alternatives", ()):
                    wrist = np.asarray(pose["arm_rad"], dtype=float)
                    shape = np.asarray(pose["positions"], dtype=float)
                    leads = tuple(float(value) for value in pose["command_leads_sec"])
                    next_note = pose.get("next_note")
                    cost_penalty = float(pose.get("cost_penalty", 0.0))
                    motion = {}
                    if "lift_positions" in pose:
                        lift = np.asarray(pose["lift_positions"], dtype=float)
                        if (lift.shape != (20,) or not np.all(np.isfinite(lift))
                                or np.any((lift < 0) | (lift > 255))):
                            raise ValueError(f"invalid lift pose for note {note}")
                        motion["lift_positions"] = lift.tolist()
                    for name in ("arm_lead_sec", "transition_sec", "prepare_lead_sec",
                                 "prepare_transition_sec"):
                        if name in pose:
                            seconds = float(pose[name])
                            if not math.isfinite(seconds) or seconds <= 0:
                                raise ValueError(f"invalid {name} for note {note}")
                            motion[name] = seconds
                    if (any(name.startswith("prepare_") for name in motion)
                            and "lift_positions" not in motion):
                        raise ValueError(f"preparation requires a lift pose for note {note}")
                    if (wrist.shape != (7,) or shape.shape != (20,) or len(leads) != 2
                            or not np.all(np.isfinite(wrist)) or not np.all(np.isfinite(shape))
                            or not all(math.isfinite(value) and value >= 0 for value in leads)
                            or not math.isfinite(cost_penalty) or cost_penalty < 0
                            or (next_note is not None
                                and (not isinstance(next_note, int) or next_note not in KEY_NOTES))):
                        raise ValueError(f"invalid alternative pose for note {note}")
                    alternatives.append((wrist, np.clip(shape, 0.0, 255.0).tolist(),
                                         leads, next_note, cost_penalty, motion))
                if alternatives:
                    self.note_alternatives[note, finger] = alternatives
                if "command_leads_sec" in values:
                    leads = tuple(float(value) for value in values["command_leads_sec"])
                    if len(leads) != 2 or not all(math.isfinite(value) and value >= 0 for value in leads):
                        raise ValueError(f"invalid press and release leads for note {note}")
                    self.note_timing[note, finger] = leads
                if "short" in values:
                    short = values["short"]
                    duration = float(short["max_duration_sec"])
                    pose = np.asarray(short["positions"], dtype=float)
                    leads = tuple(float(value) for value in short["command_leads_sec"])
                    if (not math.isfinite(duration) or duration <= 0 or pose.shape != (20,)
                            or not np.all(np.isfinite(pose)) or len(leads) != 2
                            or not all(math.isfinite(value) and value >= 0 for value in leads)):
                        raise ValueError(f"invalid short-note calibration for note {note}")
                    self.short_note_poses[note, finger] = (
                        duration, np.clip(pose, 0.0, 255.0).tolist(), leads)
                if "contact" in values:
                    contact = values["contact"]
                    if not isinstance(contact, dict):
                        raise ValueError(f"contact hint for note {note} must be a mapping")
                    orientation = tuple(float(value) for value in contact.get("orientation_deg", ()))
                    offset = tuple(float(value) for value in contact.get("offset_m", ()))
                    depth = float(contact.get("depth_m", 0))
                    seed = tuple(float(value) for value in contact.get("arm_seed_rad", ()))
                    side = contact.get("side")
                    if (len(orientation) != 3 or len(offset) != 2 or depth <= 0
                            or len(seed) not in (0, 7)
                            or side not in (None, *self.sides)
                            or not all(math.isfinite(value)
                                       for value in (*orientation, *offset, depth, *seed))):
                        raise ValueError(f"invalid contact hint for note {note}")
                    contact_key = (note, finger) if side is None else (side, note, finger)
                    self.note_contacts[contact_key] = orientation, offset, depth, seed
                if "positions" not in values:
                    continue
                values = values.get("positions")
            elif selected_finger:
                raise ValueError(f"finger-specific note {key!r} requires a pose mapping")
            values = np.asarray(values, dtype=float)
            if values.shape != (20,):
                raise ValueError(f"note override {key!r} must contain 20 values")
            self.note_overrides[note if finger is None else (note, finger)] = values
        self.ready20 = np.asarray(poses["READY"]["positions"], dtype=float)
        if self.ready20.shape != (20,):
            raise ValueError("READY pose must contain 20 values")
        self.press20 = {}
        self.delta = {}
        for letter, finger in POSE_FINGER.items():
            values = np.asarray(poses[f"PRESS_{letter}"]["positions"], dtype=float)
            if values.shape != (20,):
                raise ValueError(f"PRESS_{letter} must contain 20 values")
            self.press20[finger] = values
            self.delta[finger] = values - self.ready20
        self._cache = {}
        self.geometry_diagnostics = []

    def _contact_set(self, data=None):
        if data is None:
            data = self.work
        m.mj_forward(self.model, data)
        return {
            tuple(sorted((int(contact.geom1), int(contact.geom2))))
            for contact in data.contact[:data.ncon]
            if contact.dist <= 0.0}

    def reset_work(self):
        m.mj_resetDataKeyframe(self.model, self.work, self.key_id)
        m.mj_forward(self.model, self.work)
        return self.work

    def hand_targets(self, side, positions20):
        return np.asarray(command_positions(list(positions20)), dtype=float)

    def set_state(self, side, arm_q, positions20, ctrl=False):
        data = self.work
        targets = self.hand_targets(side, positions20)
        data.qpos[self.arm_qpos[side]] = np.asarray(arm_q, dtype=float)
        data.qpos[self.hand_qpos[side]] = targets
        if ctrl:
            data.ctrl[self.arm_act[side]] = np.asarray(arm_q, dtype=float)
            data.ctrl[self.hand_act[side]] = targets
        return data

    def compose(self, fingers, notes=None):
        pressed = {finger for finger in FINGERS if finger in set(fingers)}
        ordered = tuple(finger for finger in FINGERS if finger in pressed)
        key = "+".join(ordered)
        if len(ordered) > 1 and key in self.chord_overrides:
            return np.clip(self.chord_overrides[key], 0.0, 255.0).tolist()
        if len(ordered) == 1 and notes is not None:
            unique = {int(note) for note in notes}
            if len(unique) == 1:
                note = next(iter(unique))
                override = self.note_overrides.get(
                    (note, ordered[0]), self.note_overrides.get(note))
                if override is not None:
                    return np.clip(override, 0.0, 255.0).tolist()
        values = self.ready20.copy()
        for finger in fingers:
            values += self.delta[finger]
        return np.clip(values, 0.0, 255.0).tolist()

    def finger_order(self, note, prior):
        if prior in FINGERS:
            rest = [finger for finger in FINGERS if finger != prior]
            rest.sort(key=lambda finger: (abs(note - REFERENCE_PITCH[finger]), finger))
            return [prior] + rest
        return sorted(FINGERS, key=lambda finger: (abs(note - REFERENCE_PITCH[finger]), finger))

    def classify(self, data=None):
        keys = set()
        other = set()
        for pair in self._contact_set(data) - self.baseline:
            ga, gb = self.geom_names[pair[0]], self.geom_names[pair[1]]
            sa = ga.split("_")[0]
            sb = gb.split("_")[0]
            if sa in self.sides and sb in self.sides:
                if sa != sb:
                    other.add(tuple(sorted((ga, gb))))
                continue
            if sa not in self.sides and sb not in self.sides:
                continue
            side, robot_geom, env_geom = (sa, ga, gb) if sa in self.sides else (sb, gb, ga)
            match = self.key_re.fullmatch(env_geom)
            if match:
                keys.add((side, int(match.group(1)), robot_geom))
            else:
                other.add(tuple(sorted((ga, gb))))
        return keys, other

    def arm_posture(self, side, arm_q):
        """Return physical posture metrics for one arm configuration.

        Elbow drop and lateral offset use the shoulder as the reference.  The
        table/keybed clearances are conservative samples along the arm; they are
        ranking hints only, while actual contacts are still rejected by
        `check_group` and the continuous playback probe.
        """
        data = self.posture_data
        data.qpos[self.arm_qpos[side]] = np.asarray(arm_q, dtype=float)
        m.mj_kinematics(self.model, data)
        ids = self.arm_body[side]
        shoulder = data.xpos[ids["Link1"]].copy()
        elbow = data.xpos[ids["Link3"]].copy()
        wrist = data.xpos[ids["Link5"]].copy()
        hand = data.xpos[ids["l20_base_link"]].copy()
        upper = elbow - shoulder
        fore = wrist - elbow
        angle = math.degrees(math.acos(np.clip(
            np.dot(upper, fore) / max(1e-9, np.linalg.norm(upper) * np.linalg.norm(fore)),
            -1.0, 1.0)))
        limits = self.arm_limits[side]
        q = np.asarray(arm_q, dtype=float)
        margins = np.minimum(q - limits[:, 0], limits[:, 1] - q)
        joint = int(np.argmin(margins))
        table = math.inf
        keybed = math.inf
        for first, second in ((shoulder, elbow), (elbow, wrist), (wrist, hand)):
            for ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
                point = first + ratio * (second - first)
                if point[1] < -0.18:
                    table = min(table, float(point[2] - self.table_top))
                if point[1] > 0.10:
                    keybed = min(keybed, float(point[2] - self.key_top))
        outward = 1.0 if side == "right" else -1.0
        return {
            "shoulder": shoulder.tolist(),
            "elbow": elbow.tolist(),
            "wrist": wrist.tolist(),
            "hand": hand.tolist(),
            "elbow_drop_m": float(shoulder[2] - elbow[2]),
            "elbow_lateral_m": float(outward * (elbow[0] - shoulder[0])),
            "elbow_back_m": float(elbow[1]),
            "elbow_angle_deg": float(angle),
            "extension": float(np.linalg.norm(wrist - shoulder)
                               / max(1e-9, np.linalg.norm(upper) + np.linalg.norm(fore))),
            "joint_margin_rad": float(margins[joint]),
            "joint_margin_joint": joint + 1,
            "table_clearance_m": float(table),
            "keybed_clearance_m": float(keybed),
        }

    def posture_cost(self, posture):
        """Soft cost for the pianist-like posture; zero is the preferred band."""
        weights = POSTURE_WEIGHTS
        drop = max(0.0, POSTURE_ELBOW_DROP_M - posture["elbow_drop_m"])
        lateral = max(0.0, POSTURE_ELBOW_LATERAL_M - posture["elbow_lateral_m"])
        back = max(0.0, abs(posture["elbow_back_m"] - POSTURE_ELBOW_BACK_M)
                   - POSTURE_ELBOW_BACK_TOL_M)
        margin = max(0.0, POSTURE_JOINT_MARGIN_RAD - posture["joint_margin_rad"])
        clearance = max(
            0.0, POSTURE_TABLE_CLEARANCE_M
            - min(posture["table_clearance_m"], posture["keybed_clearance_m"]))
        return float(weights["elbow_drop"] * drop ** 2
                     + weights["elbow_lateral"] * lateral ** 2
                     + weights["elbow_back"] * back ** 2
                     + weights["joint_margin"] * margin ** 2
                     + weights["table_clearance"] * clearance ** 2)

    def continuity_cost(self, arm_q, previous):
        if previous is None:
            return 0.0
        delta = (np.asarray(arm_q, dtype=float) - np.asarray(previous, dtype=float)) / 0.7
        return float(np.mean(delta ** 2))

    def prepare_tip(self, side, finger, hand20, desired_R):
        data = self.reset_work()
        data.qpos[self.hand_qpos[side]] = self.hand_targets(side, hand20)
        data.qpos[self.arm_qpos[side]] = self.ready_arm_q[side]
        m.mj_kinematics(self.model, data)
        gid, verts = self.fingertip[(side, finger)]
        wrist_R = data.xmat[self.wrist_id[side]].reshape(3, 3)
        geom_R = data.geom_xmat[gid].reshape(3, 3)
        relative = wrist_R.T @ geom_R
        local = verts[np.argmin((verts @ (desired_R @ relative).T)[:, 2])].copy()
        self.tip_cfg[(side, finger)] = (gid, local, desired_R)

    def tip_point(self, side, finger):
        gid, local, _ = self.tip_cfg[(side, finger)]
        data = self.work
        return data.geom_xpos[gid] + data.geom_xmat[gid].reshape(3, 3) @ local

    def solve_arm(self, side, target, seed, hand20, desired_R, finger,
                  iterations=140, posture=None):
        solutions = self.solve_arm_solutions(
            side, target, [seed], hand20, desired_R, finger,
            iterations=iterations, posture=posture, limit=1)
        return None if not solutions else solutions[0]["q"]

    def solve_arm_solutions(self, side, target, seeds, hand20, desired_R, finger,
                            iterations=140, posture=None, limit=4):
        """Return several converged IK solutions ranked by soft posture cost.

        The first solution from a single seed is not privileged: every seed is
        tried with and without a null-space posture bias, and the surviving
        candidates are compared on elbow placement, joint-limit margin and
        continuity to the previous arm pose.
        """
        posture = posture or {}
        previous = posture.get("previous")
        results = []
        for seed in seeds:
            for bias in (0.0, float(posture.get("bias", 1.0))):
                solved = self._solve_arm_once(
                    side, target, seed, hand20, desired_R, finger,
                    iterations=iterations, posture=posture, bias=bias)
                if solved is None:
                    continue
                q, position_error, rotation_error = solved
                metrics = self.arm_posture(side, q)
                if metrics["joint_margin_rad"] < POSTURE_MIN_JOINT_MARGIN_RAD:
                    continue
                score = (self.posture_cost(metrics)
                         + 0.5 * self.continuity_cost(q, previous)
                         + 0.01 * (np.linalg.norm(position_error) / 0.00016
                                   + np.linalg.norm(rotation_error) / 0.004))
                results.append({"q": np.asarray(q, dtype=float), "metrics": metrics,
                                "score": float(score),
                                "position_error_m": float(np.linalg.norm(position_error)),
                                "rotation_error": float(np.linalg.norm(rotation_error))})
        unique = []
        for result in sorted(results, key=lambda item: item["score"]):
            if any(np.max(np.abs(result["q"] - other["q"])) < 0.01 for other in unique):
                continue
            unique.append(result)
            if len(unique) >= limit:
                break
        return unique

    def _solve_arm_once(self, side, target, seed, hand20, desired_R, finger,
                        iterations=140, posture=None, bias=0.0):
        data = self.reset_work()
        data.qpos[self.hand_qpos[side]] = self.hand_targets(side, hand20)
        qa = self.arm_qpos[side]
        da = self.arm_dof[side]
        limits = self.arm_limits[side]
        q = np.clip(np.asarray(seed, dtype=float), limits[:, 0], limits[:, 1])
        gid, _, _ = self.tip_cfg[(side, finger)]
        wrist = self.wrist_id[side]
        body = self.model.geom_bodyid[gid]
        elbow_body = self.arm_body[side]["Link3"]
        outward = 1.0 if side == "right" else -1.0
        previous = (posture or {}).get("previous")
        margin = float((posture or {}).get("margin", POSTURE_JOINT_MARGIN_RAD))
        margin_weight = float((posture or {}).get("margin_weight", 4.0))
        center_weight = float((posture or {}).get("center_weight", 0.05))
        continuity_weight = float((posture or {}).get("continuity_weight", 0.25))
        bias_step = float((posture or {}).get("bias_step", 0.06))
        center = 0.5 * (limits[:, 0] + limits[:, 1])
        for _ in range(iterations):
            data.qpos[qa] = q
            m.mj_kinematics(self.model, data)
            m.mj_comPos(self.model, data)
            point = self.tip_point(side, finger)
            position_error = np.asarray(target, dtype=float) - point
            actual_R = data.xmat[wrist].reshape(3, 3)
            rotation_error = 0.5 * np.cross(actual_R.T, desired_R.T).sum(axis=0)
            if (np.linalg.norm(position_error) <= 0.00016
                    and np.linalg.norm(rotation_error) <= 0.004):
                return q.copy(), position_error, rotation_error
            m.mj_jac(self.model, data, self.jp, self.jr, point, body)
            jacobian = np.vstack((self.jp[:, da], 0.13 * self.jr[:, da]))
            task = np.r_[position_error, 0.13 * rotation_error]
            pinv = jacobian.T @ np.linalg.inv(
                jacobian @ jacobian.T + np.eye(6) * 0.005 ** 2)
            delta = pinv @ task
            if bias:
                elbow = data.xpos[elbow_body]
                jp_elbow = np.zeros((3, self.model.nv))
                jr_elbow = np.zeros((3, self.model.nv))
                m.mj_jac(self.model, data, jp_elbow, jr_elbow, elbow, elbow_body)
                drop = float(data.xpos[self.arm_body[side]["Link1"]][2] - elbow[2])
                lateral = float(outward * (
                    elbow[0] - data.xpos[self.arm_body[side]["Link1"]][0]))
                back = float(elbow[1])
                grad = np.zeros(7)
                if drop < POSTURE_ELBOW_DROP_M:
                    grad += (2.0 * POSTURE_WEIGHTS["elbow_drop"]
                             * (POSTURE_ELBOW_DROP_M - drop) * -jp_elbow[2, da])
                if lateral < POSTURE_ELBOW_LATERAL_M:
                    grad += (2.0 * POSTURE_WEIGHTS["elbow_lateral"]
                             * (POSTURE_ELBOW_LATERAL_M - lateral)
                             * outward * jp_elbow[0, da])
                if abs(back - POSTURE_ELBOW_BACK_M) > POSTURE_ELBOW_BACK_TOL_M:
                    grad += (-2.0 * POSTURE_WEIGHTS["elbow_back"]
                             * (back - POSTURE_ELBOW_BACK_M) * jp_elbow[1, da])
                lower = q - limits[:, 0]
                upper = limits[:, 1] - q
                grad += 2.0 * margin_weight * (
                    np.maximum(0.0, margin - lower) - np.maximum(0.0, margin - upper))
                grad += 2.0 * center_weight * (center - q)
                if previous is not None:
                    grad += 2.0 * continuity_weight * (
                        np.asarray(previous, dtype=float) - q)
                null = (np.eye(7) - pinv @ jacobian) @ grad
                largest = float(np.max(np.abs(null)))
                if largest > bias_step:
                    null *= bias_step / largest
                delta = delta + bias * null
            scale = min(0.9, 0.15 / max(1e-9, np.max(np.abs(delta))))
            updated = np.clip(q + delta * scale, limits[:, 0], limits[:, 1])
            if np.max(np.abs(updated - q)) < 1e-7:
                return None
            q = updated
        return None

    def check_group(self, side, expected, arm_q, hand20, strict=True):
        """Check target contacts; strict mode also rejects every extra touch."""
        expected_notes = {note for note, _ in expected}
        data = self.reset_work()
        self.set_state(side, arm_q, hand20)
        m.mj_forward(self.model, data)
        over = {
            note: float(data.qpos[address])
            for note, address in self.key_qpos.items()
            if float(data.qpos[address]) > self.key_limit[note] + 1e-9}
        if over:
            return False, {"overpress": over}
        keys, other = self.classify()
        if other:
            return False, {"other_contacts": sorted(other)[:4]}
        got = {}
        for key_side, note, geom in keys:
            if key_side != side:
                return False, {"wrong_side": key_side}
            got.setdefault(note, set()).add(geom)
        penalty = 0
        extra = []
        for note, finger in expected:
            geoms = got.get(note, set())
            matching = [geom for geom in geoms if geom.startswith(f"{side}_{finger}_")]
            if not matching:
                return False, {"missing_contact": (note, finger),
                               "contacts": sorted(geoms)[:4]}
            if len(matching) != len(geoms):
                if strict:
                    return False, {"wrong_finger": note,
                                   "contacts": sorted(geoms)[:4]}
                penalty += len(geoms) - len(matching)
                extra.append({"note": note, "finger": finger, "contacts": sorted(geoms)})
        for note, geoms in got.items():
            if note in expected_notes:
                continue
            if strict:
                return False, {"extra_key": note, "contacts": sorted(geoms)[:4]}
            penalty += len(geoms)
            extra.append({"note": note, "contacts": sorted(geoms)})
        return True, {"penalty": penalty, "extra_contacts": extra}

    def dynamic_probe(self, side, notes, arm_q, hand20, settle=0.15,
                      hold=0.35, release=0.25):
        """Replay a short press with the same HandTrack used by the executor.

        The hand ready->press and press->ready transitions are smoothsteps in
        20-value command space, exactly like `run_performance.py`; the release
        phase is included when collecting extra key edges.
        """
        target = set(int(note) for note in notes)
        sim = m.MjData(self.model)
        m.mj_resetDataKeyframe(self.model, sim, self.key_id)
        arm_q = np.asarray(arm_q, dtype=float)
        ready20 = np.asarray(self.compose([]), dtype=float)
        ready_targets = self.hand_targets(side, ready20)
        sim.qpos[self.arm_qpos[side]] = arm_q
        sim.ctrl[self.arm_act[side]] = arm_q
        sim.qpos[self.hand_qpos[side]] = ready_targets
        sim.ctrl[self.hand_act[side]] = ready_targets
        m.mj_forward(self.model, sim)
        transition = float(getattr(self, "hand_transition", 0.04))
        track = HandTrack(
            ready20,
            [{"time_sec": settle, "positions": hand20},
             {"time_sec": settle + hold, "positions": ready20.tolist()}],
            transition)
        key_events = KeyEvents(self.model)
        active = set()
        seen = set()
        hold_active = None
        travel = KeyTravelMonitor(self.model)
        edges = []
        end = settle + hold + release
        while sim.time < end - 1e-9:
            sim.ctrl[self.hand_act[side]] = command_positions(
                track.at(sim.time).tolist())
            m.mj_step(self.model, sim)
            travel.observe(sim)
            for _, edge, note in key_events.update(sim):
                edges.append((edge, int(note)))
                if edge == "on":
                    active.add(int(note))
                    seen.add(int(note))
                else:
                    active.discard(int(note))
            if hold_active is None and sim.time >= settle + hold - 1e-9:
                hold_active = set(active)
            if sim.warning.number.any():
                return False, {"probe": "unstable trajectory"}
        if hold_active is None:
            hold_active = set(active)
        missing = sorted(target - hold_active)
        extra = sorted(seen - target)
        stuck = sorted(target & active)
        violations = travel.violations()
        expected_edges = sorted((edge, note) for note in target for edge in ("on", "off"))
        ok = (not missing and not extra and not stuck and not violations
              and sorted(edges) == expected_edges and not sim.warning.number.any())
        return ok, {"missing": missing, "extra": extra, "stuck": stuck,
                    "angle_violations": violations, "edges": edges,
                    "max_angle": {str(note): float(value) for note, value in
                                  zip(KEY_NOTES, travel.maximum) if value > 0.0},
                    "transition": transition}

    def candidate_group(self, side, assignments, arm_seed, fixed_arm=None,
                        prior_dev=0, prior_weight=2.0):
        """Find a pose that passes an isolated press and release."""
        for candidate in self.geometry_candidates(side, assignments, fixed_arm):
            if candidate.detail.get("next_note") is not None:
                continue
            ok, detail = self.dynamic_probe(
                side, [event["note"] for event, _ in assignments],
                candidate.arm_q, candidate.hand20)
            if ok:
                return Candidate(
                    candidate.arm_q, candidate.hand20, candidate.orientation,
                    candidate.cost + prior_weight * prior_dev,
                    {**candidate.detail, "probe": detail}, candidate.hover_arm)
        return None

    def geometry_candidates(self, side, assignments, fixed_arm=None, previous_arm=None,
                            posture_weight=1.0, continuity_weight=0.5,
                            ik_candidate_limit=2):
        """Check geometry only. Dynamics depend on the preceding trajectory.

        ``fixed_arm`` is a hard constraint for a held-note hand pose.  A new
        reachable pose is otherwise ranked with the soft posture cost, using
        ``previous_arm`` for a null-space seed and a continuity penalty.
        """
        fingers = [finger for _, finger in assignments]
        hand20 = self.compose(
            fingers, [event["note"] for event, _ in assignments])
        expected = [(event["note"], finger) for event, finger in assignments]
        previous = None if previous_arm is None else np.asarray(previous_arm, dtype=float)

        def make_candidate(arm_q, shape, orientation, base_cost, detail, hover=None):
            metrics = self.arm_posture(side, arm_q)
            posture_cost = self.posture_cost(metrics)
            continuity = self.continuity_cost(arm_q, previous)
            detail = {**detail, "posture": metrics, "posture_cost": posture_cost,
                      "continuity_cost": continuity}
            return Candidate(
                np.asarray(arm_q, dtype=float).copy(), shape, orientation,
                base_cost + posture_weight * posture_cost + continuity_weight * continuity,
                detail, hover, metrics)

        if fixed_arm is not None:
            fixed_arm = np.asarray(fixed_arm, dtype=float)
            variants = [(hand20, {})]
            if len(assignments) == 1 and expected[0] in self.short_note_poses:
                max_duration, pose, leads = self.short_note_poses[expected[0]]
                event = assignments[0][0]
                if event["end"] - event["start"] <= max_duration:
                    variants.append((pose, {"command_leads_sec": leads, "short_pose": True}))
            candidates = []
            for shape, variant in variants:
                ok, detail = self.check_group(side, expected, fixed_arm, shape, strict=False)
                attempt = {"side": side, "assignments": expected, "arm": fixed_arm.tolist(),
                           "accepted": ok, "fixed_arm": True, **variant, **detail}
                self.geometry_diagnostics.append(attempt)
                if ok:
                    candidates.append(make_candidate(
                        fixed_arm, shape, (0, 0, 0),
                        0.5 * detail.get("penalty", 0) + (0.05 if variant else 0.0),
                        attempt))
            return candidates
        seed_key = None if previous is None else tuple(np.round(previous, 3))
        cache_key = (side, tuple(expected), seed_key)
        if cache_key in self._cache:
            return self._cache[cache_key]
        seed = self.ready_arm_q[side]
        candidates = []
        single = len(assignments) == 1
        if previous is not None:
            ok, detail = self.check_group(side, expected, previous, hand20, strict=False)
            attempt = {"side": side, "assignments": expected, "arm": previous.tolist(),
                       "accepted": ok, "reuse_previous_arm": True, **detail}
            self.geometry_diagnostics.append(attempt)
            if ok:
                candidates.append(make_candidate(
                    previous, hand20, (0, 0, 0), 0.5 * detail.get("penalty", 0), attempt))
        if single:
            bounds = self.arm_limits[side]
            for wrist, shape, leads, next_note, cost_penalty, motion in self.note_alternatives.get(expected[0], ()):
                if not np.all((wrist >= bounds[:, 0]) & (wrist <= bounds[:, 1])):
                    continue
                ok, detail = self.check_group(side, expected, wrist, shape, strict=False)
                attempt = {"side": side, "assignments": expected, "alternative_wrist": wrist.tolist(),
                           "accepted": ok, "command_leads_sec": leads, "next_note": next_note,
                           "cost_penalty": cost_penalty,
                           **motion, **detail}
                self.geometry_diagnostics.append(attempt)
                if ok:
                    candidates.append(make_candidate(
                        wrist, shape, (0, 0, 0),
                        cost_penalty + 0.5 * detail.get("penalty", 0), attempt))
        chord = "+".join(sorted(fingers, key=FINGERS.index))
        if chord in self.chord_arm_seeds:
            wrist = self.chord_arm_seeds[chord]
            bounds = self.arm_limits[side]
            if np.all((wrist >= bounds[:, 0]) & (wrist <= bounds[:, 1])):
                ok, detail = self.check_group(side, expected, wrist, hand20, strict=False)
                attempt = {"side": side, "assignments": expected, "calibrated_wrist": wrist.tolist(),
                           "accepted": ok, **detail}
                self.geometry_diagnostics.append(attempt)
                if ok:
                    candidates.append(make_candidate(
                        wrist, hand20, (0, 0, 0), 0.0, attempt))
        contact = self.note_contacts.get((side, *expected[0]),
                                         self.note_contacts.get(expected[0])) if single else None
        depth = contact[2] if contact else self.press_depth
        if single:
            stages = (
                (True, self.strict_orientations, self.strict_offsets, seed),
                (False, self.relax_orientations, self.relax_offsets, seed),
            )
        else:
            stages = (
                (True, self.chord_strict_orientations, self.chord_strict_offsets, seed),
                (False, self.chord_relax_orientations, self.relax_offsets, seed),
            )
        if contact:
            orientation, offset, _, preferred_seed = contact
            stages = ((False, (orientation,), (offset,), preferred_seed or seed),) + stages
        for strict, orientations, offsets, arm_seed in stages:
            for orientation in orientations:
                desired_R = orientation_rotation(orientation, self.play_R)
                for event, primary_finger in assignments:
                    base = self.points[event["note"] - 21]
                    self.prepare_tip(side, primary_finger, hand20, desired_R)
                    for dx, dy in offsets:
                        target = base + np.array([dx, dy, -depth])
                        attempt = {"side": side, "assignments": expected,
                                   "orientation": orientation, "target": target.tolist(),
                                   "strict": strict}
                        seeds = []
                        if previous is not None:
                            seeds.append(previous)
                        seeds.append(np.asarray(arm_seed, dtype=float))
                        seeds.append(0.5 * (self.arm_limits[side][:, 0]
                                            + self.arm_limits[side][:, 1]))
                        unique_seeds = []
                        for item in seeds:
                            if not any(np.max(np.abs(item - other)) < 1e-6
                                       for other in unique_seeds):
                                unique_seeds.append(item)
                        solutions = self.solve_arm_solutions(
                            side, target, unique_seeds, hand20, desired_R, primary_finger,
                            posture={"previous": previous}, limit=ik_candidate_limit)
                        if not solutions:
                            self.geometry_diagnostics.append(
                                {**attempt, "accepted": False, "ik_failed": True})
                            continue
                        for solution in solutions:
                            arm_q = solution["q"]
                            ok, detail = self.check_group(
                                side, expected, arm_q, hand20, strict=strict)
                            self.geometry_diagnostics.append(
                                {**attempt, "accepted": ok,
                                 "ik_score": solution["score"], **detail})
                            if not ok:
                                continue
                            if any(item.hand20 == hand20
                                   and np.max(np.abs(item.arm_q - arm_q)) < 1e-6
                                   for item in candidates):
                                continue
                            cost = (0.5 * detail.get("penalty", 0)
                                    + sum(map(abs, orientation)) / 30.0)
                            hover = self.solve_arm(
                                side, target + np.array([0.0, 0.0, 0.05]),
                                arm_q, self.compose([]), desired_R, primary_finger,
                                posture={"previous": arm_q, "bias": 0.5})
                            candidates.append(make_candidate(
                                arm_q, hand20, orientation, cost,
                                {**attempt, **detail, "ik_score": solution["score"]},
                                hover))
        self._cache[cache_key] = candidates
        return candidates


class FingeringPlanner:
    """Search candidates per hand and verify paired tracks for a dual-hand plan."""

    def __init__(self, model, *, beam_width=8, candidate_limit=3,
                 prior_weight=2.0, travel_weight=1.0, posture_weight=2.0,
                 continuity_weight=0.5, ik_candidate_limit=2,
                 arm_move_speed=SIM_ARM_SPEED,
                 arm_safety=None, arm_lead=0.10, start_padding=1.0,
                 press_lead=0.05, release_lead=0.07, hand_transition=0.04,
                 min_hand_interval=0.04, timing_tolerance=0.03,
                 tempo_scale=1.0, fingering_mode="auto", planning_budget_sec=300.0,
                 fast=False, dynamic_prefix=True, progress=None):
        self.model = model
        self.progress = progress
        self.beam_width = int(beam_width)
        self.candidate_limit = int(candidate_limit)
        self.prior_weight = float(prior_weight)
        self.travel_weight = float(travel_weight)
        self.posture_weight = float(posture_weight)
        self.continuity_weight = float(continuity_weight)
        self.ik_candidate_limit = int(ik_candidate_limit)
        self.arm_move_speed = float(arm_move_speed)
        self.arm_safety = (float(model.model.opt.timestep)
                           if arm_safety is None else float(arm_safety))
        self.arm_lead = float(arm_lead)
        self.start_padding = float(start_padding)
        self.press_lead = float(press_lead)
        self.release_lead = float(release_lead)
        self.hand_transition = float(hand_transition)
        self.min_hand_interval = float(min_hand_interval)
        self.timing_tolerance = float(timing_tolerance)
        self.tempo_scale = float(tempo_scale)
        self.fingering_mode = fingering_mode
        self.planning_budget_sec = float(planning_budget_sec)
        if fingering_mode not in ("fixed", "auto"):
            raise ValueError("fingering_mode must be fixed or auto")
        if not 0 < self.beam_width:
            raise ValueError("beam_width must be positive")
        if not math.isfinite(self.planning_budget_sec) or self.planning_budget_sec <= 0:
            raise ValueError("planning_budget_sec must be finite and positive")
        if not 0 < self.arm_move_speed:
            raise ValueError("arm_move_speed must be positive")
        if not math.isfinite(self.travel_weight) or self.travel_weight < 0:
            raise ValueError("travel_weight must be finite and non-negative")
        if not math.isfinite(self.posture_weight) or self.posture_weight < 0:
            raise ValueError("posture_weight must be finite and non-negative")
        if not math.isfinite(self.continuity_weight) or self.continuity_weight < 0:
            raise ValueError("continuity_weight must be finite and non-negative")
        if self.ik_candidate_limit <= 0:
            raise ValueError("ik_candidate_limit must be positive")
        if not 0 < self.min_hand_interval:
            raise ValueError("min_hand_interval must be positive")
        if self.start_padding < 0 or self.press_lead < 0 or self.release_lead < 0:
            raise ValueError("padding and leads must not be negative")
        self.model.hand_transition = self.hand_transition
        self.fast = bool(fast)
        self.dynamic_prefix = bool(dynamic_prefix)
        if self.fast:
            # Layout/regression mode: one flat wrist with the two useful key
            # offsets.  The full candidate sweep remains the default.
            self.model.strict_orientations = (
                (0, 0, 0), (-10, 0, 0), (10, 0, 0), (0, -6, 0), (0, 6, 0),
                (-20, 0, 0))
            self.model.relax_orientations = self.model.strict_orientations
            self.model.chord_strict_orientations = ((0, 0, 0), (0, -12, 0), (0, 12, 0))
            self.model.chord_relax_orientations = ((0, 0, 0), (0, -12, 0), (0, 12, 0))
            self.model.strict_offsets = ((0.0, 0.0), (0.0, -0.038))
            self.model.relax_offsets = ((0.0, 0.0), (0.0, -0.038))
        self.diagnostics = []

    def _check_budget(self, stage):
        if time.monotonic() - self.started >= self.planning_budget_sec:
            raise PlanningError(
                f"planning budget exhausted ({self.planning_budget_sec:g} s) during {stage}")

    def plan(self, events, hand="right", left_max_note=59, source=None, joint_check=None):
        self.started = time.monotonic()
        self.diagnostics.clear()
        self.model.geometry_diagnostics.clear()
        if hand not in ("left", "right", "both"):
            raise ValueError("hand must be left, right or both")
        by_hand = events_by_hand(events, left_max_note)
        sides = ("left", "right") if hand == "both" else (hand,)
        for side, selected in by_hand.items():
            if side not in sides and selected:
                raise ValueError(f"{side} hand events are present; choose both hands or filter the score")
            if side in sides and not selected:
                raise ValueError(f"no {side}-hand events")
        if self.fingering_mode == "fixed":
            missing = [event["id"] for event in events if event.get("finger") is None]
            if missing:
                raise ValueError(f"fixed fingering requires a finger for each event: {missing}")
        if hand != "both":
            groups = group_events(by_hand[hand], self.model.chord_epsilon)
            final = self._plan_hand(hand, groups)
            return self._build_plan(hand, final, source, left_max_note)
        if joint_check is None:
            raise ValueError("both-hand planning requires a joint playback checker")
        validate_physical_key_spans(
            ((event["start"], event["end"], event["note"]) for event in events),
            str(source) if source is not None else "<events>")
        beams = [
            self._plan_hand(side, group_events(by_hand[side], self.model.chord_epsilon),
                            return_beam=True)
            for side in sides
        ]
        pairs = sorted(
            itertools.product(*beams),
            key=lambda pair: sum(state["cost"] for state in pair)
            + self._pair_posture_cost(*pair))
        for index, pair in enumerate(pairs):
            self._check_budget("joint playback")
            left, right = [self._build_plan(side, state, source, left_max_note)
                           for side, state in zip(sides, pair)]
            plan = {**right, "metadata": {**right["metadata"], "hand": "both"},
                    "hands": {**left["hands"], **right["hands"]}}
            report = joint_check(plan)
            self.diagnostics.append({"stage": "joint_playback", "pair": index,
                                     "report": report})
            self._check_budget("joint playback")
            if report["passed"]:
                return plan
        raise PlanningError(
            f"joint playback rejected all {len(pairs)} candidate pairs; see joint_playback diagnostics")

    def _pair_posture_cost(self, left, right):
        """Soft dual-arm separation cost for the first planned poses."""
        left_q = left["waypoints"][0]["joints"]
        right_q = right["waypoints"][0]["joints"]
        left_elbow = self.model.arm_posture("left", left_q)["elbow"]
        right_elbow = self.model.arm_posture("right", right_q)["elbow"]
        separation = float(right_elbow[0] - left_elbow[0])
        return 2.0 * max(0.0, 0.30 - separation) ** 2

    def _assignments(self, group, active_fingers):
        lists = []
        for event in group["notes"]:
            order = ([event["finger"]] if self.fingering_mode == "fixed" else
                     self.model.finger_order(event["note"], event.get("finger")))
            choices = [finger for finger in order if finger not in active_fingers]
            lists.append(choices[:self.candidate_limit])
        if any(not choices for choices in lists):
            return
        for combination in itertools.product(*lists):
            if len(set(combination)) != len(combination):
                continue
            yield list(zip(group["notes"], combination))

    def _initial_state(self, side):
        arm = self.model.ready_arm_q[side].copy()
        return {
            "cost": 0.0,
            "arm": arm,
            "active": [],
            "path": [],
            "checkpoint": None,
        }

    def _plan_hand(self, side, groups, *, return_beam=False,
                   initial_beam=None, group_offset=0):
        if initial_beam is None:
            beam = [self._initial_state(side)]
        else:
            beam = list(initial_beam)
            if not beam:
                raise ValueError("initial_beam must not be empty")
        for group_index, group in enumerate(groups, start=group_offset):
            stage = f"{side} hand at {group['start']:.3f}s"
            self._check_budget(stage)
            following = groups[group_index + 1]["notes"] if group_index + 1 < len(groups) else ()
            next_notes = {event["note"] for event in following}
            next_states = []
            failures = set()
            pruned = 0
            for state in beam:
                active = [item for item in state["active"]
                          if item[0]["end"] > group["start"] + 1e-6]
                for assignment in self._assignments(group, [finger for _, finger in active]):
                    after = active + assignment
                    prior_dev = sum(event.get("finger") not in (None, finger)
                                    for event, finger in assignment)
                    assignment_cost = state["cost"] + self.prior_weight * prior_dev
                    if self._outside_beam(next_states, assignment_cost):
                        pruned += 1
                        continue
                    if active:
                        candidates = self.model.geometry_candidates(
                            side, after, fixed_arm=state["arm"], previous_arm=state["arm"],
                            posture_weight=self.posture_weight,
                            continuity_weight=self.continuity_weight,
                            ik_candidate_limit=self.ik_candidate_limit)
                    else:
                        candidates = self.model.geometry_candidates(
                            side, after, previous_arm=state["arm"],
                            posture_weight=self.posture_weight,
                            continuity_weight=self.continuity_weight,
                            ik_candidate_limit=self.ik_candidate_limit)
                        candidates = [
                            candidate for candidate in candidates
                            if candidate.detail.get("next_note") is None
                            or candidate.detail["next_note"] in next_notes]
                    self._check_budget(stage)
                    if not candidates:
                        failures.add("held-note contact" if active else "no reachable finger/arm pose")
                    if state["path"]:
                        # Rank by total soft cost first; joint distance is the tie-breaker.
                        candidates = sorted(candidates, key=lambda item: (
                            item.cost, np.max(np.abs(item.arm_q - state["arm"]))))
                    trials = 0
                    tested_poses = set()
                    for index, candidate in enumerate(candidates):
                        pose = (candidate.arm_q.tobytes(), tuple(candidate.hand20),
                                candidate.detail.get("command_leads_sec"))
                        if pose in tested_poses:
                            continue
                        tested_poses.add(pose)
                        if self._outside_beam(next_states, assignment_cost + candidate.cost):
                            pruned += 1
                            continue
                        path, reason = self._schedule_candidate(
                            side, group, state, assignment, after, candidate)
                        self._check_budget(stage)
                        if reason != "insufficient motion time":
                            trials += 1
                        if path is None:
                            failures.add(reason)
                        else:
                            path["cost"] += self.prior_weight * prior_dev
                            next_states.append(path)
                        if trials >= self.beam_width:
                            if index + 1 < len(candidates):
                                failures.add("pose trial limit reached")
                            break
            if not next_states:
                raise PlanningError(
                    f"no plan for {side} at {group['start']:.3f}s "
                    f"(notes {[event['note'] for event in group['notes']]}): "
                    f"{sorted(failures) or ['no compatible assignment']}")
            if len(next_states) > self.beam_width:
                self.diagnostics.append({"start_sec": group["start"], "reason": "beam truncation",
                                         "discarded": len(next_states) - self.beam_width})
            if pruned:
                self.diagnostics.append({"start_sec": group["start"], "reason": "beam cost bound",
                                         "discarded": pruned})
            beam = sorted(next_states, key=lambda item: item["cost"])[:self.beam_width]
            if self.progress is not None:
                self.progress(
                    side=side, group_index=group_index, group_count=len(groups),
                    start_sec=group["start"], candidate_count=len(next_states),
                    beam_width=len(beam), elapsed_sec=time.monotonic() - self.started)
        return beam if return_beam else min(beam, key=lambda item: item["cost"])

    def _outside_beam(self, states, cost):
        if len(states) < self.beam_width:
            return False
        return cost >= sorted(state["cost"] for state in states)[self.beam_width - 1]

    def _schedule_candidate(self, side, group, state, assignment, after, candidate):
        on = self.start_padding + group["start"]
        dt = self.model.model.opt.timestep / self.tempo_scale
        base_press = self.press_lead
        shortest = min(event["end"] - group["start"] for event, _ in assignment)
        fingers = "+".join(sorted((finger for _, finger in after), key=FINGERS.index))
        transition = candidate.detail.get(
            "transition_sec", self.model.chord_transitions.get(fingers, self.hand_transition))
        if "lift_positions" in candidate.detail and (len(assignment) != 1 or len(after) != 1):
            return None, "lift preparation would interrupt a held note"
        base_press += max(0.0, transition - self.hand_transition) * 2 / 3
        # Initial guesses only. Re-evaluate any correction against continuous dynamics.
        leads = [(base_press, self.release_lead)]
        if shortest < self.min_hand_interval + self.hand_transition:
            leads = [(base_press, base_press), (base_press + self.hand_transition, self.release_lead),
                     (base_press + self.hand_transition, self.release_lead + 0.012),
                     (base_press + self.hand_transition, base_press + self.hand_transition)]
            if shortest < self.hand_transition:
                # Start with a pulse close to the control transition time. An
                # interrupted release is still validated by measured key edges.
                pulse = max(shortest, self.hand_transition + 2 * dt)
                leads.insert(0, (base_press, max(0., base_press + shortest - pulse)))
        if len(assignment) == 1:
            event, finger = assignment[0]
            hint = candidate.detail.get("command_leads_sec",
                                        self.model.note_timing.get((event["note"], finger)))
            if hint is not None and hint not in leads:
                leads.insert(0, hint)
        travel = float(np.max(np.abs(candidate.arm_q - state["arm"])))
        moving = bool(state["path"]) and travel > 1e-6
        failures = set()
        routes = ("direct", "lift") if moving else ("direct",)
        for route, (press_lead, off_lead) in itertools.product(routes, leads):
            press = max(0.0, on - press_lead)
            releases = {event["id"]: max(press + dt, self.start_padding + event["end"] - off_lead)
                        for event, _ in assignment}
            for _ in range(2):
                waypoints, budget = self._arm_timing(
                    state, candidate, group["start"], press, dt, route)
                if waypoints is None:
                    failures.add("insufficient motion time")
                    self._log_trial(
                        group, candidate, press, releases, "insufficient motion time", budget)
                    break
                arm_index = len(waypoints) - 1
                entry = {"assignments": assignment, "candidate": candidate, "press_sec": press,
                         "release_secs": releases, "arm_index": arm_index,
                         "transition_sec": transition,
                         "pose_event_ids": {event["id"] for event, _ in after}}
                if "lift_positions" in candidate.detail:
                    previous_events = [event for old in state["path"]
                                       for event, _ in old["assignments"]]
                    free = max((max(
                        self.start_padding + event["end"],
                        state["observed"].get(event["id"], {}).get(
                            "off", (self.start_padding + event["end"])
                            * self.tempo_scale) / self.tempo_scale)
                        for event in previous_events), default=0.0)
                    prepare = max(free + self.arm_safety / self.tempo_scale,
                                  press - candidate.detail.get("prepare_lead_sec", .06))
                    if prepare > press - dt + 1e-9:
                        reason = "insufficient lift preparation time"
                        failures.add(reason)
                        self._log_trial(group, candidate, press, releases, reason, budget)
                        break
                    entry["prepare_sec"] = prepare
                path = state["path"] + [entry]
                try:
                    hand_states = self._hand_states(path, dt)
                except PlanningError as error:
                    failures.add(str(error))
                    self._log_trial(group, candidate, press, releases, str(error), budget)
                    break
                if self.dynamic_prefix:
                    edges, reason, checkpoint = self._probe_prefix(
                        side, path, waypoints, hand_states, state["checkpoint"],
                        budget["waypoints"][0]["move_after_sec"] if moving else None)
                else:
                    # Geometry/timing search only; the final PlanRunner still
                    # performs the strict continuous playback check.
                    edges, reason, checkpoint = {}, None, None
                self._log_trial(group, candidate, press, releases, reason, budget, edges)
                if reason is None:
                    return {
                        "arm": candidate.arm_q.copy(), "active": after, "path": path,
                        "waypoints": waypoints, "hand_states": hand_states, "checkpoint": checkpoint,
                        "observed": edges,
                        "cost": state["cost"] + candidate.cost
                        + (self.travel_weight * travel / 0.5 if moving else 0.0),
                    }, None
                failures.add(reason)
                if reason != "note timing":
                    break
                new_press, new_releases = self._correct_timing(press, releases, edges, dt)
                if max(abs(press - new_press), *(abs(releases[key] - new_releases[key])
                                                 for key in releases)) < dt / 2:
                    break
                press, releases = new_press, new_releases
        return None, ", ".join(sorted(failures))

    def _correct_timing(self, press, releases, edges, dt):
        """Use the smallest measured correction, preserving a playable pulse."""
        scale = self.tempo_scale
        release_changes = {}
        errors = []
        for event_id in releases:
            measurement = edges[event_id]
            error = measurement["duration_error"]
            tolerance = measurement["duration_tolerance"]
            excess = math.copysign(max(0.0, abs(error) - tolerance), error)
            ticks = math.ceil(abs(excess) / (dt * scale))
            change = math.copysign(ticks * dt, excess)
            release_changes[event_id] = change
            errors.extend((measurement["on_error"], measurement["off_error"] - change * scale))
        low = (max(errors) - self.timing_tolerance) / scale
        high = (min(errors) + self.timing_tolerance) / scale
        if low > high:
            shift = (low + high) / 2
        elif low > 0:
            shift = min(high, math.ceil(low / dt) * dt)
        elif high < 0:
            shift = max(low, math.floor(high / dt) * dt)
        else:
            shift = 0.0
        corrected_press = max(0.0, press - shift)
        return corrected_press, {
            event_id: max(corrected_press + dt, sec - shift - release_changes[event_id])
            for event_id, sec in releases.items()
        }

    def _log_trial(self, group, candidate, press, releases, reason, budget=None, edges=None):
        measured = {
            event["id"]: {**edges[event["id"]],
                          "press_delay_sec": edges[event["id"]]["on"] - press * self.tempo_scale,
                          "release_delay_sec": edges[event["id"]]["off"]
                          - releases[event["id"]] * self.tempo_scale}
            for event in group["notes"] if edges and event["id"] in edges
        }
        self.diagnostics.append({
            "start_sec": group["start"], "notes": [event["note"] for event in group["notes"]],
            "arm": candidate.arm_q.tolist(), "geometry": candidate.detail,
            "press_command_sec": press, "release_commands_sec": releases,
            "result": reason or "passed", "budget": budget, "events": measured,
        })

    def _arm_timing(self, state, candidate, start, press, dt, route):
        if not state["path"]:
            return ([{"time_sec": 0.0, "move_after_sec": 0.0,
                      "joints": candidate.arm_q.tolist()}], {"move_sec": 0.0})
        previous = state["arm"]
        if np.max(np.abs(candidate.arm_q - previous)) <= 1e-6:
            return state["waypoints"], {"move_sec": 0.0}
        events = [event for entry in state["path"] for event, _ in entry["assignments"]]
        if any(event["end"] > start + 1e-6 for event in events):
            return None, {"route": route, "held_note": True}
        free = max(
            max(self.start_padding + event["end"],
                state["observed"].get(event["id"], {}).get("off", 0.0)
                / self.tempo_scale)
            for event in events)
        depart = free + self.arm_safety / self.tempo_scale
        settle = 2 * dt
        target_joints = [candidate.arm_q]
        if route == "lift":
            source = state["path"][-1]["candidate"].hover_arm
            target = candidate.hover_arm
            if source is None or target is None:
                return None, {"route": route, "missing_hover": True}
            target_joints = [source, target, candidate.arm_q]
        segments = []
        for joints in target_joints:
            distance = float(np.max(np.abs(joints - previous)))
            if distance > 1e-6:
                segments.append((joints, 1.5 * distance / (self.arm_move_speed * self.tempo_scale)))
                previous = joints
        minimum = sum(duration for _, duration in segments)
        latest = press - settle
        budget = {
            "route": route, "free_sec": free, "available_move_sec": latest - depart,
            "minimum_move_sec": minimum, "press_lead_sec": self.start_padding + start - press,
            "settle_sec": settle, "safety_sec": self.arm_safety / self.tempo_scale,
            "waypoints": [joints.tolist() for joints, _ in segments],
        }
        if latest - depart < minimum - 1e-9:
            return None, budget
        preferred = self.start_padding + start - candidate.detail.get("arm_lead_sec", self.arm_lead)
        arrival = max(depart + minimum, min(latest, preferred))
        begin = depart
        waypoints = []
        for joints, duration in segments:
            end = begin + (arrival - depart) * duration / minimum
            waypoints.append({"time_sec": end, "move_after_sec": begin, "joints": joints.tolist()})
            begin = end
        budget["move_sec"] = arrival - depart
        budget["waypoints"] = waypoints
        return state["waypoints"] + waypoints, budget

    def _hand_states(self, path, dt):
        actions = {}
        release_lifts = {}
        for entry in path:
            press = round(entry["press_sec"], 9)
            transition = entry.get("transition_sec", self.hand_transition)
            add = actions.setdefault(press, [[], [], [], []])
            add[1].extend(entry["assignments"])
            add[2].append(transition)
            add[3].append(entry)
            for event, _ in entry["assignments"]:
                if "lift_positions" in entry["candidate"].detail:
                    release_lifts[event["id"]] = entry["candidate"].detail["lift_positions"]
                off = round(entry["release_secs"][event["id"]], 9)
                remove = actions.setdefault(off, [[], [], [], []])
                remove[0].append(event["id"])
                remove[2].append(transition)
        active = {}
        states = []
        for time_sec, (releases, presses, transitions, pose_entries) in sorted(actions.items()):
            previous = "+".join(sorted((finger for _, finger in active.values()), key=FINGERS.index))
            for event_id in releases:
                active.pop(event_id, None)
            active.update({event["id"]: (event, finger) for event, finger in presses})
            fingers = sorted((finger for _, finger in active.values()), key=FINGERS.index)
            if len(set(fingers)) != len(fingers):
                raise PlanningError("two hand commands need the same finger")
            if states and time_sec - states[-1]["time_sec"] < dt - 1e-8:
                raise PlanningError("hand commands are less than one physics step apart")
            notes = [event["note"] for event, _ in active.values()]
            positions = self.model.compose(fingers, notes)
            for entry in pose_entries:
                if entry["pose_event_ids"] == active.keys():
                    positions = entry["candidate"].hand20
            if releases and not presses and len(fingers) == 1:
                positions = self.model.chord_release_poses.get((previous, fingers[0]), positions)
            if len(releases) == 1 and not presses and not fingers:
                positions = release_lifts.get(releases[0], positions)
            states.append({"time_sec": time_sec, "pressed": fingers,
                           "positions": positions,
                           "transition_sec": max(transitions)})
        for entry in path:
            if "prepare_sec" not in entry:
                continue
            prepare = entry["prepare_sec"]
            if any(self.start_padding + event["start"] <= prepare
                   < self.start_padding + event["end"]
                   for old in path for event, _ in old["assignments"]):
                raise PlanningError("lift preparation would interrupt a held note")
            states.append({"time_sec": prepare, "pressed": [],
                           "positions": entry["candidate"].detail["lift_positions"],
                           "transition_sec": entry["candidate"].detail.get(
                               "prepare_transition_sec", .025)})
        states.sort(key=lambda item: item["time_sec"])
        if any(second["time_sec"] - first["time_sec"] < dt - 1e-8
               for first, second in zip(states, states[1:])):
            raise PlanningError("hand commands are less than one physics step apart")
        return states

    def _probe_prefix(self, side, path, waypoints, states, previous, move_after=None):
        model = self.model
        tempo = self.tempo_scale
        sim = m.MjData(model.model)
        ready = path[0]["candidate"].detail.get("lift_positions", model.compose([]))
        first = np.asarray(waypoints[0]["joints"])
        arm = ArmTrack(first, [
            {**wp, "time_sec": wp["time_sec"] * tempo,
             "move_after_sec": wp["move_after_sec"] * tempo} for wp in waypoints])
        hand = HandTrack(ready, [
            {**item, "time_sec": item["time_sec"] * tempo,
             "transition_sec": item["transition_sec"] * tempo} for item in states],
            self.hand_transition * tempo)
        keys = KeyEvents(model.model)
        travel = KeyTravelMonitor(model.model)
        integration = m.mjtState.mjSTATE_INTEGRATION
        press = path[-1]["press_sec"] * tempo
        moving = move_after is not None
        begin = min(press, move_after * tempo) if moving else press
        begin = min(begin, path[-1].get("prepare_sec", path[-1]["press_sec"]) * tempo)
        timestep = float(model.model.opt.timestep)
        first_tick = math.ceil((begin - 1e-9) / timestep) * timestep
        if previous is None:
            m.mj_resetDataKeyframe(model.model, sim, model.key_id)
            sim.qpos[model.arm_qpos[side]] = sim.ctrl[model.arm_act[side]] = first
            targets = model.hand_targets(side, ready)
            sim.qpos[model.hand_qpos[side]] = sim.ctrl[model.hand_act[side]] = targets
            m.mj_forward(model.model, sim)
            edges = []
        else:
            eligible = [item for item in previous if item[0] <= first_tick + 1e-9]
            if not eligible:
                return {}, "new command precedes continuous state", None
            _, snapshot, old_edges, active_keys = eligible[-1]
            m.mj_setState(model.model, sim, snapshot, integration)
            m.mj_forward(model.model, sim)
            edges = list(old_edges)
            keys._active.update(active_keys)
        events = [item for entry in path for item in entry["assignments"]]
        score_end = (self.start_padding + max(event["end"] for event, _ in events)) * tempo
        end = score_end + 0.15
        cut_times = [begin, score_end]
        checkpoints = []
        settled = not moving
        by_note = {}
        for event, finger in events:
            by_note.setdefault(event["note"], []).append((event, finger))
        while sim.time < end - 1e-9:
            if cut_times and sim.time >= cut_times[0] - 1e-9:
                snapshot = np.empty(m.mj_stateSize(model.model, integration))
                m.mj_getState(model.model, sim, snapshot, integration)
                checkpoints.append((sim.time, snapshot, tuple(edges), frozenset(keys._active)))
                cut_times = [time_sec for time_sec in cut_times if time_sec > sim.time + 1e-9]
            if moving and not settled and sim.time >= press - 1e-9:
                error = np.max(np.abs(sim.qpos[model.arm_qpos[side]] - arm.at(press)))
                speed = np.max(np.abs(sim.qvel[model.arm_dof[side]]))
                if error > SIM_ARM_SETTLE_ERROR or speed > SIM_ARM_SETTLE_SPEED:
                    return {}, f"wrist not settled ({error:.4f} rad, {speed:.3f} rad/s)", None
                settled = True
            sim.ctrl[model.arm_act[side]] = arm.at(sim.time)
            sim.ctrl[model.hand_act[side]] = model.hand_targets(side, hand.at(sim.time))
            m.mj_step(model.model, sim)
            if sim.warning.number.any():
                return {}, "unstable trajectory", None
            new_edges = keys.update(sim)
            edges.extend(new_edges)
            contacts, other = model.classify(sim)
            if other:
                return {}, f"collision {sorted(other)}", None
            for _, edge, note in new_edges:
                if edge == "on" and note not in by_note:
                    return {}, f"unexpected key {note}", None
            for key_side, note, geom in contacts:
                if note not in keys._active:
                    continue
                expected = [finger for event, finger in by_note.get(note, ())
                            if ((self.start_padding + event["start"]) * tempo - 0.04
                                <= sim.time <=
                                (self.start_padding + event["end"]) * tempo + 0.04)]
                if key_side != side or not any(
                        s == side and n == note and g.startswith(f"{side}_{finger}_")
                        for s, n, g in contacts for finger in expected):
                    return {}, f"wrong finger on key {note} ({geom})", None
            travel.observe(sim)
        violations = travel.violations()
        if violations:
            return {}, "key angle limit " + str(violations), None
        measured = {}
        timing_ok = True
        for note, items in by_note.items():
            actual = [(t, edge) for t, edge, n in edges if n == note]
            if [edge for _, edge in actual] != ["on", "off"] * len(items):
                return {}, f"missing or repeated key {note}: {actual}", None
            for (event, _), ((on, _), (off, _)) in zip(items, zip(actual[::2], actual[1::2])):
                on_error = on - (self.start_padding + event["start"]) * tempo
                off_error = off - (self.start_padding + event["end"]) * tempo
                duration = (event["end"] - event["start"]) * tempo
                tolerance = note_duration_tolerance(
                    duration, self.timing_tolerance, model.model.opt.timestep)
                timing_ok &= (abs(on_error) <= self.timing_tolerance
                              and abs(off_error) <= self.timing_tolerance
                              and abs(off_error - on_error) <= tolerance)
                measured[event["id"]] = {"on": on, "off": off, "on_error": on_error,
                                          "off_error": off_error,
                                          "duration_error": off_error - on_error,
                                          "duration_tolerance": tolerance}
        return measured, None if timing_ok else "note timing", checkpoints

    def _build_plan(self, side, state, source, left_max_note):
        data = self.model
        events = []
        for entry in state["path"]:
            for event, finger in entry["assignments"]:
                events.append({
                    "id": event["id"], "note": event["note"],
                    "start_sec": self.start_padding + event["start"],
                    "end_sec": self.start_padding + event["end"],
                    "velocity": event["velocity"], "finger": finger,
                    "prior_finger": event.get("finger"), "arm_waypoint": entry["arm_index"],
                })
        events.sort(key=lambda item: (item["start_sec"], item["note"]))
        hand_states = state["hand_states"]
        ready_state = state["path"][0]["candidate"].detail.get("lift_positions", data.compose([]))
        arm_waypoints = state["waypoints"]
        plan = {
            "format": "piano_performance/1",
            "metadata": {
                "score": str(source) if source is not None else "",
                "hand": side,
                "layout": data.scene_config,
                "tempo_scale": self.tempo_scale,
                "fingering_mode": self.fingering_mode,
                "start_padding_sec": self.start_padding,
                "arm_lead_sec": self.arm_lead,
                "press_lead_sec": self.press_lead,
                "release_lead_sec": self.release_lead,
                "hand_transition_sec": self.hand_transition,
                "press_depth_m": data.press_depth,
                "timing_tolerance_sec": self.timing_tolerance,
                "left_max_note": left_max_note,
                "planner": {
                    "beam_width": self.beam_width,
                    "candidate_limit": self.candidate_limit,
                    "planning_budget_sec": self.planning_budget_sec,
                    "prior_weight": self.prior_weight,
                    "arm_move_speed": self.arm_move_speed,
                    "arm_safety": self.arm_safety,
                    "arm_settle_error_rad": SIM_ARM_SETTLE_ERROR,
                    "arm_settle_speed_rad_sec": SIM_ARM_SETTLE_SPEED,
                    "min_hand_interval": self.min_hand_interval,
                    "posture_weight": self.posture_weight,
                    "continuity_weight": self.continuity_weight,
                    "ik_candidate_limit": self.ik_candidate_limit,
                },
                "posture": {
                    "elbow_drop_target_m": POSTURE_ELBOW_DROP_M,
                    "elbow_lateral_target_m": POSTURE_ELBOW_LATERAL_M,
                    "elbow_back_target_m": POSTURE_ELBOW_BACK_M,
                    "joint_margin_target_rad": POSTURE_JOINT_MARGIN_RAD,
                    "min_joint_margin_rad": POSTURE_MIN_JOINT_MARGIN_RAD,
                },
            },
            "hands": {
                side: {
                    "ready_state": ready_state,
                    "arm_start": state["waypoints"][0]["joints"],
                    "arm_waypoints": arm_waypoints,
                    "posture": [data.arm_posture(side, waypoint["joints"])
                                for waypoint in arm_waypoints],
                    "hand_states": hand_states,
                    "events": events,
                }
            },
        }
        return plan


class PlanningError(RuntimeError):
    pass
