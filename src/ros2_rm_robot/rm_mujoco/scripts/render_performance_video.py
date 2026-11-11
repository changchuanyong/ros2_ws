#!/usr/bin/env python3
"""Replay a piano_performance/1 plan and write a split-screen MuJoCo video.

Left: overview camera.  Right: side camera (looking along +x), so the
shoulder-elbow-wrist chain and the key contact height are both visible.
"""

import argparse
import math
from pathlib import Path
import subprocess
import sys
import tempfile

import mujoco as m
import numpy as np

try:
    from ament_index_python.packages import get_package_share_directory
except ImportError:
    get_package_share_directory = None

from rm_mujoco.keyboard import KeyEvents, KeyHighlight
from rm_mujoco.l20_joint_mapping import HAND_JOINT_SUFFIXES, command_positions
from rm_mujoco.performance import load_plan
from rm_mujoco.performance_runtime import ArmTrack, HandTrack
from rm_mujoco.scene import build_model, load_layout


def default_package():
    if get_package_share_directory is not None:
        try:
            return Path(get_package_share_directory("rm_mujoco"))
        except Exception:
            pass
    return Path(__file__).resolve().parents[1]


def camera(kind):
    view = m.MjvCamera()
    view.type = m.mjtCamera.mjCAMERA_FREE
    view.lookat[:] = [0.0, 0.32, 0.90]
    view.distance = 2.35 if kind == "overview" else 2.10
    view.azimuth = 155.0 if kind == "overview" else 0.0
    view.elevation = -18.0 if kind == "overview" else -5.0
    return view


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", type=Path, default=None)
    parser.add_argument("--scene-config", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    args = parser.parse_args(argv)
    package = (args.package or default_package()).resolve()
    scene = args.scene_config.resolve()
    plan = load_plan(args.plan)
    tempo = float(plan["metadata"].get("tempo_scale", 1.0))
    layout = load_layout(scene)
    with tempfile.TemporaryDirectory(prefix="piano_video_") as directory:
        model_path = build_model(package / "models/rm_75_6fb_v_dual_l20.xml",
                                 layout, directory, movable_keys=True)
        model = m.MjModel.from_xml_path(str(model_path))
        data = m.MjData(model)
        m.mj_resetDataKeyframe(model, data, model.key("piano_ready").id)
        arm_act = {}
        arm_track = {}
        hand_act = {}
        hand_track = {}
        for side, hand in plan["hands"].items():
            arm_joints = [model.joint(f"{side}_joint{i}") for i in range(1, 8)]
            arm_act[side] = np.array([
                int(np.flatnonzero(model.actuator_trnid[:, 0] == joint.id)[0])
                for joint in arm_joints])
            hand_joints = [model.joint(f"{side}_{suffix}") for suffix in HAND_JOINT_SUFFIXES]
            hand_act[side] = np.array([
                int(np.flatnonzero(model.actuator_trnid[:, 0] == joint.id)[0])
                for joint in hand_joints])
            data.qpos[[int(joint.qposadr[0]) for joint in arm_joints]] = \
                np.asarray(hand["arm_start"], dtype=float)
            data.ctrl[arm_act[side]] = np.asarray(hand["arm_start"], dtype=float)
            ready = np.asarray(command_positions(hand["ready_state"]), dtype=float)
            data.qpos[[int(joint.qposadr[0]) for joint in hand_joints]] = ready
            data.ctrl[hand_act[side]] = ready
            arm_track[side] = ArmTrack(hand["arm_start"], hand["arm_waypoints"])
            transition = float(plan["metadata"].get("hand_transition_sec", 0.04))
            states = [{"time_sec": item["time_sec"] * tempo,
                       "positions": item["positions"],
                       "transition_sec": float(item.get("transition_sec", transition)) * tempo}
                      for item in hand["hand_states"]]
            hand_track[side] = HandTrack(
                np.asarray(hand["ready_state"], dtype=float), states, transition * tempo)
        m.mj_forward(model, data)
        key_events = KeyEvents(model)
        highlight = KeyHighlight(model)
        end = max(
            [event["end_sec"] * tempo for hand in plan["hands"].values()
             for event in hand["events"]]
            + [item["time_sec"] * tempo for hand in plan["hands"].values()
               for item in hand["hand_states"]]
            + [item["time_sec"] * tempo for hand in plan["hands"].values()
               for item in hand["arm_waypoints"]]) + 0.6
        frames = int(math.ceil(end * args.fps)) + 1
        args.output.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = subprocess.Popen([
            "ffmpeg", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{args.width * 2}x{args.height}", "-r", str(args.fps), "-i", "-",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
            str(args.output)], stdin=subprocess.PIPE)
        try:
            with m.Renderer(model, height=args.height, width=args.width) as left, \
                    m.Renderer(model, height=args.height, width=args.width) as right:
                for frame in range(frames):
                    target_time = frame / args.fps
                    while data.time < target_time - 1e-9:
                        for side in plan["hands"]:
                            data.ctrl[arm_act[side]] = arm_track[side].at(data.time)
                            data.ctrl[hand_act[side]] = command_positions(
                                hand_track[side].at(data.time).tolist())
                        m.mj_step(model, data)
                        key_events.update(data)
                    highlight.set_pressed(set(key_events._active))
                    left.update_scene(data, camera=camera("overview"))
                    right.update_scene(data, camera=camera("side"))
                    image = np.concatenate([left.render(), right.render()], axis=1)
                    ffmpeg.stdin.write(image.tobytes())
                    if frame % 60 == 0:
                        print(f"frame {frame}/{frames} t={data.time:.2f}", flush=True)
        finally:
            ffmpeg.stdin.close()
            ffmpeg.wait()
        print(f"WROTE {args.output} frames={frames} fps={args.fps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
