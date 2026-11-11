#!/usr/bin/env python3
"""Render the chosen 88-key reachability poses from three fixed views."""

import argparse
import json
import math
from pathlib import Path
import struct
import sys
import zlib

import mujoco as m
import numpy as np

try:
    from ament_index_python.packages import get_package_share_directory
except ImportError:
    get_package_share_directory = None

from rm_mujoco.fingering import PianoHandModel
from rm_mujoco.performance import FINGERS


def default_package():
    if get_package_share_directory is not None:
        try:
            return Path(get_package_share_directory("rm_mujoco"))
        except Exception:
            pass
    return Path(__file__).resolve().parents[1]


def write_png(path, pixels):
    height, width, _ = pixels.shape

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    raw = b"".join(b"\0" + row.tobytes() for row in pixels)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def label(image, text):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return image
    picture = Image.fromarray(image)
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, 0, picture.width, 34), fill=(20, 22, 26))
    draw.text((12, 8), text, fill=(240, 240, 240))
    return np.asarray(picture)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", type=Path, default=None)
    parser.add_argument("--scene-config", type=Path, required=True)
    parser.add_argument("--pose-file", type=Path, default=None)
    parser.add_argument("--reachability", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--press-depth", type=float, default=0.0075)
    parser.add_argument("--notes", default="21,60,108")
    args = parser.parse_args(argv)
    package = (args.package or default_package()).resolve()
    scene = args.scene_config.resolve()
    pose = (args.pose_file or package / "config/right_hand_piano_sim.yaml").resolve()
    model = PianoHandModel(package, scene, pose, press_depth=args.press_depth)
    document = json.loads(args.reachability.read_text(encoding="utf-8"))
    records = document["records"]
    args.output.mkdir(parents=True, exist_ok=True)
    metrics = {}
    for note in (int(value) for value in args.notes.split(",")):
        selected = [record for record in records
                    if record["note"] == note and record.get("dynamic")
                    and record.get("arm_q")]
        # Prefer the side whose arm has the larger elbow drop, but keep both
        # sides if both are dynamically valid (mid-keyboard overlap).
        selected.sort(key=lambda item: item["posture"]["elbow_drop_m"], reverse=True)
        for record in selected[:2]:
            side = record["side"]
            finger = (record.get("dynamic_finger") or record["fingers"][0])
            if finger not in FINGERS:
                continue
            hand20 = model.compose([finger], [note])
            data = model.reset_work()
            data.qpos[model.arm_qpos[side]] = np.asarray(record["arm_q"], dtype=float)
            data.qpos[model.hand_qpos[side]] = model.hand_targets(side, hand20)
            m.mj_forward(model.model, data)
            key = f"{side}_{note:03d}"
            metrics[key] = {
                "side": side, "note": note, "finger": finger,
                "posture": record["posture"],
                "orientation_deg": record.get("orientation_deg"),
                "offset_m": record.get("offset_m"),
                "dynamic": record.get("dynamic"),
            }
            for view in ("front", "side", "overview", "keys"):
                with m.Renderer(model.model, height=720, width=1280) as renderer:
                    if view == "side":
                        camera = m.MjvCamera()
                        camera.type = m.mjtCamera.mjCAMERA_FREE
                        camera.lookat[:] = [0.0, 0.35, 0.88]
                        camera.distance = 2.2
                        camera.azimuth = 0.0
                        camera.elevation = -6.0
                        renderer.update_scene(data, camera=camera)
                    else:
                        renderer.update_scene(data, camera=view)
                    image = renderer.render()
                text = (f"MIDI {note} {side} {finger}  drop="
                        f"{record['posture']['elbow_drop_m']:.3f} m  margin="
                        f"{record['posture']['joint_margin_rad']:.3f} rad")
                write_png(args.output / f"{key}_{view}.png", label(image, text))
            print(f"RENDER {key} {finger} views=4")
    (args.output / "posture_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"WROTE {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
