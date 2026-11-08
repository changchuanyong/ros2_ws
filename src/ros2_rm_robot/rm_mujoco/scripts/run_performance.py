#!/usr/bin/env python3
"""Play a `piano_performance/1` plan in the passive-key MuJoCo scene.

The plan already contains the arm waypoints and full 20-value L20 hand states.
This script builds the model, converts each hand state to the 21 MuJoCo hand
joints, samples one continuous control track at the physics timestep, and
compares the actual passive-key edges with the plan.  It is simulation-only;
no ROS controller, MoveIt or RS485 code is used.

Usage:
    python3 run_performance.py --plan song.performance.yaml --output /tmp/song_sim
"""

import argparse
import json
import math
from pathlib import Path
import re
import struct
import sys
import tempfile

import mujoco as m
import numpy as np

try:
    from ament_index_python.packages import get_package_share_directory
except ImportError:  # source-tree use before sourcing an install
    get_package_share_directory = None

from rm_mujoco.keyboard import KEY_NOTES, KeyEvents, KeyHighlight, key_joint_name
from rm_mujoco.l20_joint_mapping import HAND_JOINT_SUFFIXES, command_positions
from rm_mujoco.performance import load_plan, maximum_live_keys
from rm_mujoco.performance_runtime import (
    ArmTrack, HandTrack, KeyTravelMonitor, KEY_LIMIT_TOLERANCE_RAD, KEY_REBOUND_TOLERANCE_RAD,
    note_duration_tolerance,
)
from rm_mujoco.scene import build_model, load_layout


class PlanRunner:
    def __init__(self, plan, package, scene_config, model_path, tempo_scale,
                 timing_tolerance, press_deg, release_deg, snapshots=None,
                 camera="keys"):
        self.plan = plan
        self.package = Path(package)
        self.tempo = float(tempo_scale)
        self.timing_tolerance = float(timing_tolerance)
        self.press_deg = press_deg
        self.release_deg = release_deg
        self.snapshots = Path(snapshots) if snapshots else None
        self.camera = camera
        self.layout = load_layout(scene_config)
        self.tmp = tempfile.TemporaryDirectory(prefix="piano_run_")
        path = build_model(model_path, self.layout, self.tmp.name, movable_keys=True)
        self.model = m.MjModel.from_xml_path(str(path))
        self.data = m.MjData(self.model)
        m.mj_resetDataKeyframe(self.model, self.data, self.model.key("piano_ready").id)
        self.geom_names = [
            self.model.geom(i).name or self.model.body(self.model.geom_bodyid[i]).name
            for i in range(self.model.ngeom)]
        self.key_re = re.compile(r"^piano_key_(\d+)(?:_rear)?$")
        self.baseline = None
        self.arm_qpos = {}
        self.arm_act = {}
        self.hand_qpos = {}
        self.hand_act = {}
        self.arm_tracks = {}
        self.hand_tracks = {}
        self._build_tracks()
        self.data.time = 0.0
        m.mj_forward(self.model, self.data)
        self.baseline = self._contact_set()
        self.key_events = KeyEvents(
            self.model, press_deg=press_deg, release_deg=release_deg)
        self.expected = self._expected_events()
        self.expected_by_note = {}
        for event in self.expected:
            self.expected_by_note.setdefault(event["note"], []).append(event)
        self.key_qpos = {}
        self.key_limits = {}
        self.key_press_thresholds = {}
        self.key_release_thresholds = {}
        for note in self.expected_by_note:
            joint = self.model.joint(key_joint_name(note))
            limit = float(joint.range[1])
            if press_deg is None:
                press = 0.55 * limit
                release = 0.30 * limit
            else:
                press = limit - math.radians(press_deg)
                release = limit - math.radians(release_deg)
            self.key_qpos[note] = int(joint.qposadr[0])
            self.key_limits[note] = limit
            self.key_press_thresholds[note] = press
            self.key_release_thresholds[note] = release
        self.key_travel = KeyTravelMonitor(self.model)
        self.key_angle_track = []
        self.tracking = []
        self._track_next = 0.0
        self.contact_tolerance = max(0.04, self.timing_tolerance + 0.01)
        self.unexpected_contacts = set()
        self.wrong_finger_contacts = set()
        self.raw_contacts = []
        self._active_contacts = set()
        self.active_key_notes = set()
        self.edges = []
        self.snapshot_times = self._snapshot_times()
        self.next_snapshot = 0
        self.highlight = KeyHighlight(self.model) if self.snapshots else None

    def _build_tracks(self):
        tempo = self.tempo
        for side, hand in self.plan["hands"].items():
            arm_joints = [self.model.joint(f"{side}_joint{i}") for i in range(1, 8)]
            self.arm_qpos[side] = np.array([int(joint.qposadr[0]) for joint in arm_joints])
            self.arm_act[side] = np.array([
                int(np.flatnonzero(self.model.actuator_trnid[:, 0] == joint.id)[0])
                for joint in arm_joints])
            hand_joints = [self.model.joint(f"{side}_{suffix}")
                           for suffix in HAND_JOINT_SUFFIXES]
            self.hand_qpos[side] = np.array([int(joint.qposadr[0]) for joint in hand_joints])
            self.hand_act[side] = np.array([
                int(np.flatnonzero(self.model.actuator_trnid[:, 0] == joint.id)[0])
                for joint in hand_joints])
            self.data.qpos[self.arm_qpos[side]] = np.asarray(hand["arm_start"], dtype=float)
            ready = np.asarray(command_positions(hand["ready_state"]), dtype=float)
            self.data.qpos[self.hand_qpos[side]] = ready
            self.data.ctrl[self.arm_act[side]] = np.asarray(hand["arm_start"], dtype=float)
            self.data.ctrl[self.hand_act[side]] = ready
            waypoints = [
                {"time_sec": float(item["time_sec"]) * tempo,
                 "move_after_sec": float(item["move_after_sec"]) * tempo,
                 "joints": item["joints"]}
                for item in hand["arm_waypoints"]]
            self.arm_tracks[side] = ArmTrack(hand["arm_start"], waypoints)
            transition = float(self.plan["metadata"].get("hand_transition_sec", 0.04))
            states = [
                {"time_sec": float(item["time_sec"]) * tempo,
                 "positions": item["positions"],
                 "transition_sec": float(item.get("transition_sec", transition)) * tempo}
                for item in hand["hand_states"]]
            self.hand_tracks[side] = HandTrack(
                np.asarray(hand["ready_state"], dtype=float), states, transition * tempo)
        m.mj_forward(self.model, self.data)

    def _expected_events(self):
        expected = []
        for side, hand in self.plan["hands"].items():
            for event in hand["events"]:
                expected.append({
                    "side": side,
                    "note": int(event["note"]),
                    "on": float(event["start_sec"]) * self.tempo,
                    "off": float(event["end_sec"]) * self.tempo,
                    "finger": event["finger"],
                    "prior_finger": event.get("prior_finger"),
                    "id": event.get("id"),
                    "arm_waypoint": event.get("arm_waypoint"),
                })
        expected.sort(key=lambda item: (item["on"], item["side"], item["note"]))
        return expected

    def _snapshot_times(self):
        if self.snapshots is None or not self.expected:
            return []
        times = {self.expected[0]["on"] + 0.1, self.expected[-1]["off"] + 0.1}
        for event in self.expected:
            if any(other["on"] == event["on"] and other["note"] != event["note"]
                   for other in self.expected):
                times.add(event["on"] + 0.1)
                break
        return sorted(times)

    def _contact_set(self):
        m.mj_forward(self.model, self.data)
        return {
            tuple(sorted((int(contact.geom1), int(contact.geom2))))
            for contact in self.data.contact[:self.data.ncon]
            if contact.dist <= 0.0}

    def _classify(self):
        keys = set()
        other = set()
        for pair in self._contact_set() - self.baseline:
            ga, gb = self.geom_names[pair[0]], self.geom_names[pair[1]]
            sa, sb = ga.split("_")[0], gb.split("_")[0]
            if sa in ("left", "right") and sb in ("left", "right"):
                if sa != sb:
                    other.add(tuple(sorted((ga, gb))))
                continue
            if sa not in ("left", "right") and sb not in ("left", "right"):
                continue
            side, robot, env = (sa, ga, gb) if sa in ("left", "right") else (sb, gb, ga)
            match = self.key_re.fullmatch(env)
            if match:
                keys.add((side, int(match.group(1)), robot))
            else:
                other.add(tuple(sorted((ga, gb))))
        return keys, other

    def _expected_finger(self, note, time_sec):
        for event in self.expected_by_note.get(note, ()):
            if event["on"] - self.contact_tolerance <= time_sec <= \
                    event["off"] + self.contact_tolerance:
                return event
        return None

    def _check_contacts(self, time_sec):
        keys, other = self._classify()
        current = set()
        for side, note, geom in keys:
            current.add((side, note, geom))
            # A finger resting on a released key is not a wrong key press; only
            # an actually-down key needs the expected finger among its contacts.
            if note not in self.active_key_notes:
                continue
            event = self._expected_finger(note, time_sec)
            contacts = [
                contact_geom for contact_side, contact_note, contact_geom in keys
                if contact_side == side and contact_note == note]
            if event is None or event["side"] != side or not any(
                    contact_geom.startswith(f"{side}_{event['finger']}_")
                    for contact_geom in contacts):
                self.wrong_finger_contacts.add((round(time_sec, 4), side, note, geom))
        for item in sorted(current - self._active_contacts):
            self.raw_contacts.append({"time_sec": round(time_sec, 4), "type": "on",
                                      "side": item[0], "note": item[1], "geom": item[2]})
        for item in sorted(self._active_contacts - current):
            self.raw_contacts.append({"time_sec": round(time_sec, 4), "type": "off",
                                      "side": item[0], "note": item[1], "geom": item[2]})
        self._active_contacts = current
        for item in other:
            self.unexpected_contacts.add(item)
        return other

    def _render_snapshot(self, time_sec):
        from rm_mujoco.render import write_png

        if self.highlight is not None:
            pressed = {note for note, _ in self._active_contacts}
            self.highlight.set_pressed(pressed)
        name = f"snapshot_{len(self.raw_contacts):04d}_{time_sec:.2f}.png"
        path = self.snapshots / name
        with m.Renderer(self.model, height=720, width=1280) as renderer:
            renderer.update_scene(self.data, camera=self.camera)
            write_png(path, renderer.render())
        return str(path)

    def run(self):
        if self.snapshots is not None:
            self.snapshots.mkdir(parents=True, exist_ok=True)
        last_event = max([event["off"] for event in self.expected] or [0.0])
        last_state = max(
            [state["time_sec"] for hand in self.plan["hands"].values()
             for state in hand["hand_states"]] or [0.0]) * self.tempo
        last_arm = max(
            [waypoint["time_sec"] for hand in self.plan["hands"].values()
             for waypoint in hand["arm_waypoints"]] or [0.0]) * self.tempo
        end = max(last_event, last_state, last_arm) + 0.6
        while self.data.time < end:
            for side, track in self.arm_tracks.items():
                self.data.ctrl[self.arm_act[side]] = track.at(self.data.time)
            for side, track in self.hand_tracks.items():
                self.data.ctrl[self.hand_act[side]] = command_positions(
                    track.at(self.data.time).tolist())
            before = self.data.time
            m.mj_step(self.model, self.data)
            if self.data.time <= before or self.data.warning.number.any():
                raise RuntimeError("unstable MuJoCo trajectory")
            for time_sec, edge, note in self.key_events.update(self.data):
                self.edges.append((float(time_sec), edge, int(note)))
                if edge == "on":
                    self.active_key_notes.add(int(note))
                else:
                    self.active_key_notes.discard(int(note))
            self._check_contacts(self.data.time)
            angles = self.key_travel.observe(self.data)
            self.key_angle_track.append({
                "time_sec": round(self.data.time, 6),
                "angles_deg": {str(note): round(float(value), 6)
                               for note, value in zip(KEY_NOTES, np.degrees(angles))},
            })
            if self.data.time >= self._track_next:
                hands = {}
                for side, arm_track in self.arm_tracks.items():
                    hand_track = self.hand_tracks[side]
                    hands[side] = {
                        "arm_target": [float(value) for value in arm_track.at(self.data.time)],
                        "arm_qpos": [
                            float(value) for value in self.data.qpos[self.arm_qpos[side]]],
                        "hand_target20": [
                            float(value) for value in hand_track.at(self.data.time)],
                        "hand_qpos21": [
                            float(value) for value in self.data.qpos[self.hand_qpos[side]]],
                    }
                self.tracking.append({
                    "time_sec": round(self.data.time, 4), "hands": hands})
                self._track_next += 0.02
            if (self.snapshots is not None and self.next_snapshot < len(self.snapshot_times)
                    and self.data.time >= self.snapshot_times[self.next_snapshot]):
                self._render_snapshot(self.data.time)
                self.next_snapshot += 1
        return self._report()

    def _actual_spans(self):
        pressed = {}
        spans = []
        for time_sec, edge, note in self.edges:
            if edge == "on":
                pressed[note] = time_sec
            elif note in pressed:
                start = pressed.pop(note)
                spans.append((start, note, time_sec - start))
        return spans

    def _match_events(self, spans):
        """Match expected and observed notes one-to-one by the smallest time error.

        The closest-first assignment prevents a late repeated note from stealing
        the earlier expected event and hiding a missing chord tone.
        """
        by_note = {}
        for start, note, duration in spans:
            by_note.setdefault(note, []).append((start, duration))
        pairs = []
        for expected_index, event in enumerate(self.expected):
            for actual_index, (start, duration) in enumerate(by_note.get(event["note"], [])):
                pairs.append((abs(start - event["on"]), expected_index,
                              actual_index, event["note"]))
        pairs.sort()
        used_expected = set()
        used_actual = set()
        matched_by_expected = {}
        for _, expected_index, actual_index, note in pairs:
            if expected_index in used_expected or (note, actual_index) in used_actual:
                continue
            used_expected.add(expected_index)
            used_actual.add((note, actual_index))
            matched_by_expected[expected_index] = actual_index
        missing = []
        extra = []
        matched = []
        onset_errors = []
        release_errors = []
        for expected_index, event in enumerate(self.expected):
            actual_index = matched_by_expected.get(expected_index)
            if actual_index is None:
                missing.append(event)
                continue
            start, duration = by_note[event["note"]][actual_index]
            onset_error = start - event["on"]
            release_error = start + duration - event["off"]
            expected_duration = event["off"] - event["on"]
            duration_error = duration - expected_duration
            duration_tolerance = note_duration_tolerance(
                expected_duration, self.timing_tolerance, self.model.opt.timestep)
            onset_errors.append(abs(onset_error))
            release_errors.append(abs(release_error))
            record = {
                "id": event["id"], "side": event["side"], "note": event["note"],
                "finger": event["finger"], "prior_finger": event["prior_finger"],
                "expected_on": event["on"], "expected_off": event["off"],
                "observed_on": start, "observed_off": start + duration,
                "onset_error": onset_error, "release_error": release_error,
                "duration_error": duration_error, "duration_tolerance_sec": duration_tolerance,
            }
            matched.append(record)
            if (abs(onset_error) > self.timing_tolerance
                    or abs(release_error) > self.timing_tolerance):
                extra.append({**record, "kind": "timing"})
            if abs(duration_error) > duration_tolerance:
                extra.append({**record, "kind": "duration"})
        for note, items in by_note.items():
            for index, (start, duration) in enumerate(items):
                if (note, index) not in used_actual:
                    extra.append({"note": note, "observed_on": start,
                                  "duration": duration, "kind": "extra"})
        return matched, missing, extra, onset_errors, release_errors

    def _arm_moves_over_held(self):
        problems = []
        for side, hand in self.plan["hands"].items():
            for index, waypoint in enumerate(hand["arm_waypoints"]):
                if index == 0:
                    continue
                start = float(waypoint["move_after_sec"]) * self.tempo
                end = float(waypoint["time_sec"]) * self.tempo
                for event in self.expected:
                    if event["side"] == side and event["on"] < end and event["off"] > start:
                        problems.append({
                            "side": side, "waypoint": index, "note": event["note"],
                            "move": [start, end], "held": [event["on"], event["off"]]})
        return problems

    def _report(self):
        spans = self._actual_spans()
        matched, missing, extra, onset_errors, release_errors = self._match_events(spans)
        arm_problems = self._arm_moves_over_held()
        live = {
            side: maximum_live_keys(hand["events"])
            for side, hand in self.plan["hands"].items()}
        chord_groups = []
        for side, hand in self.plan["hands"].items():
            starts = sorted({round(event["start_sec"], 6) for event in hand["events"]})
            for start in starts:
                notes = [event["note"] for event in hand["events"]
                         if round(event["start_sec"], 6) == start]
                if len(notes) > 1:
                    chord_groups.append({"side": side, "start_sec": start, "notes": notes})
        deviations = [
            {"id": event["id"], "note": event["note"],
             "prior_finger": event["prior_finger"], "finger": event["finger"]}
            for event in self.expected
            if event["prior_finger"] is not None
            and event["prior_finger"] != event["finger"]]
        active_at_end = sorted(self.active_key_notes)
        limit_details = self.key_travel.violations()
        angle_violations = [item["note"] for item in limit_details]
        passed = (not missing and not extra and not arm_problems
                  and not self.unexpected_contacts and not self.wrong_finger_contacts
                  and not active_at_end and not angle_violations
                  and all(value <= 5 for value in live.values()))
        report = {
            "passed": passed,
            "plan": {
                "format": self.plan["format"],
                "metadata": self.plan["metadata"],
                "hands": {
                    side: {
                        "events": len(hand["events"]),
                        "arm_waypoints": len(hand["arm_waypoints"]),
                        "hand_states": len(hand["hand_states"]),
                    } for side, hand in self.plan["hands"].items()},
            },
            "tempo_scale": self.tempo,
            "timing_tolerance_sec": self.timing_tolerance,
            "key_activation_deg": {"press": self.press_deg, "release": self.release_deg},
            "active_keys_at_end": active_at_end,
            "angle_violations": angle_violations,
            "angle_violation_details": limit_details,
            "key_limit_tolerance_rad": KEY_LIMIT_TOLERANCE_RAD,
            "key_rebound_tolerance_rad": KEY_REBOUND_TOLERANCE_RAD,
            "all_key_angle_max_deg": {
                str(note): float(value) for note, value in
                zip(KEY_NOTES, np.degrees(self.key_travel.maximum))},
            "all_key_angle_min_deg": {
                str(note): float(value) for note, value in
                zip(KEY_NOTES, np.degrees(self.key_travel.minimum))},
            "key_angles": {
                str(note): {
                    "max_angle_deg": math.degrees(self.key_travel.maximum[note - KEY_NOTES.start]),
                    "press_threshold_deg": math.degrees(
                        self.key_press_thresholds[note]),
                    "release_threshold_deg": math.degrees(
                        self.key_release_thresholds[note]),
                    "limit_deg": math.degrees(self.key_limits[note]),
                } for note in sorted(self.key_qpos)},
            "key_state_transitions": len(self.edges),
            "expected_events": self.expected,
            "observed": matched,
            "missing": missing,
            "unexpected": extra,
            "max_onset_error_sec": max(onset_errors) if onset_errors else None,
            "max_release_error_sec": max(release_errors) if release_errors else None,
            "max_live_keys_per_hand": live,
            "same_hand_chords": chord_groups,
            "arm_moves_over_held_notes": arm_problems,
            "unexpected_contacts": sorted(str(item) for item in self.unexpected_contacts),
            "wrong_finger_contacts": sorted(str(item) for item in self.wrong_finger_contacts),
            "fingering_deviations": deviations,
            "raw_contact_transitions": len(self.raw_contacts),
            "left_hand": "not used; this phase plans the right hand only"
            if "left" not in self.plan["hands"] else "simulated from plan",
        }
        return report


def _variable_length(value):
    result = [value & 0x7F]
    while value > 0x7F:
        value >>= 7
        result.insert(0, (value & 0x7F) | 0x80)
    return bytes(result)


def write_observed_midi(path, spans):
    events = []
    for start, note, duration in spans:
        on = round(start * 960)
        off = max(round((start + duration) * 960), on + 1)
        events.append((on, 1, 0, note, 85))
        events.append((off, 0, 0, note, 0))
    events.sort(key=lambda item: (item[0], item[1]))
    track = bytearray(b"\x00\xff\x51\x03\x07\xa1\x20")
    previous = 0
    for tick, kind, channel, note, velocity in events:
        track += _variable_length(tick - previous)
        track += bytes(((0x90 if kind else 0x80) | channel, note, velocity))
        previous = tick
    track += b"\x00\xff\x2f\x00"
    path.write_bytes(
        b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
        + b"MTrk" + struct.pack(">I", len(track)) + bytes(track))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package", type=Path, default=None,
                        help="rm_mujoco source or share directory")
    parser.add_argument("--scene-config", type=Path, default=None)
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--tempo-scale", type=float, default=None)
    parser.add_argument("--timing-tolerance", type=float, default=None)
    parser.add_argument("--key-press-deg", type=float, default=None)
    parser.add_argument("--key-release-deg", type=float, default=None)
    parser.add_argument("--snapshots", type=Path, default=None)
    parser.add_argument("--camera", choices=("overview", "front", "keys"), default="keys")
    args = parser.parse_args(argv)
    if (args.key_press_deg is None) != (args.key_release_deg is None):
        parser.error("--key-press-deg and --key-release-deg must be given together")
    if args.key_press_deg is not None and not 0 <= args.key_press_deg < args.key_release_deg:
        parser.error("key thresholds must satisfy 0 <= press < release")
    try:
        plan = load_plan(args.plan)
        if args.package is not None:
            package = args.package
        elif get_package_share_directory is not None:
            package = Path(get_package_share_directory("rm_mujoco"))
        else:
            package = Path(__file__).resolve().parents[1]
        scene_config = args.scene_config or package / "config/piano_scene.yaml"
        model_path = args.model or package / "models/rm_75_6fb_v_dual_l20.xml"
        tempo = args.tempo_scale
        if tempo is None:
            tempo = float(plan["metadata"].get("tempo_scale", 1.0))
        if not math.isfinite(tempo) or tempo <= 0:
            parser.error("tempo scale must be finite and positive")
        tolerance = args.timing_tolerance
        if tolerance is None:
            tolerance = float(plan["metadata"].get("timing_tolerance_sec", 0.03))
        if not math.isfinite(tolerance) or tolerance <= 0:
            parser.error("timing tolerance must be finite and positive")
        runner = PlanRunner(
            plan, package, scene_config, model_path, tempo, tolerance,
            args.key_press_deg, args.key_release_deg, args.snapshots, args.camera)
        report = runner.run()
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
        (args.output / "raw_contacts.json").write_text(
            json.dumps(runner.raw_contacts, indent=2), encoding="utf-8")
        (args.output / "key_edges.json").write_text(
            json.dumps(runner.edges, indent=2), encoding="utf-8")
        (args.output / "key_angle_track.json").write_text(
            json.dumps(runner.key_angle_track), encoding="utf-8")
        (args.output / "tracking.jsonl").write_text(
            "\n".join(json.dumps(item) for item in runner.tracking) + "\n",
            encoding="utf-8")
        write_observed_midi(
            args.output / "played_keys.mid",
            [(item["observed_on"], item["note"],
              item["observed_off"] - item["observed_on"]) for item in report["observed"]])
        print(
            f"RESULT passed={report['passed']} expected={len(report['expected_events'])} "
            f"observed={len(report['observed'])} missing={len(report['missing'])} "
            f"unexpected={len(report['unexpected'])} "
            f"chords={len(report['same_hand_chords'])} "
            f"max_onset_error={report['max_onset_error_sec']}")
        if not report["passed"]:
            print("DETAILS", json.dumps({
                "missing": report["missing"][:3],
                "unexpected": report["unexpected"][:3],
                "arm_moves_over_held": report["arm_moves_over_held_notes"][:3],
                "unexpected_contacts": report["unexpected_contacts"][:3],
                "wrong_finger_contacts": report["wrong_finger_contacts"][:3],
            }))
            return 3
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
