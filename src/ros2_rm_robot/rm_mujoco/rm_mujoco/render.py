"""Render the actual MuJoCo piano scene without starting ROS or hardware."""

import argparse
from pathlib import Path
import struct
import tempfile
import zlib

from ament_index_python.packages import get_package_share_directory
import mujoco
from rm_mujoco.keyboard import KeyHighlight, key_joint_name
from rm_mujoco.scene import build_model, load_layout


def write_png(path, pixels):
    """Save an RGB renderer frame without an additional imaging dependency."""
    height, width, _ = pixels.shape

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    raw = b"".join(b"\0" + row.tobytes() for row in pixels)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    )


def main():
    share = Path(get_package_share_directory("rm_mujoco"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-config", type=Path, default=share / "config/piano_scene.yaml")
    parser.add_argument("--camera", default="overview", choices=("overview", "front", "keys"))
    parser.add_argument("--press-notes", default="",
                        help="comma-separated MIDI notes to press with a test torque")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        pressed = [int(note) for note in arguments.press_notes.split(",") if note.strip()]
    except ValueError:
        parser.error("--press-notes expects comma-separated MIDI numbers")
    if any(note not in range(21, 109) for note in pressed):
        parser.error("--press-notes must be within MIDI notes 21-108")
    layout = load_layout(arguments.scene_config)
    with tempfile.TemporaryDirectory(prefix="rm75_render_") as directory:
        model_path = build_model(
            share / "models/rm_75_6fb_v_dual_l20.xml", layout, directory,
            movable_keys=bool(pressed)
        )
        model = mujoco.MjModel.from_xml_path(str(model_path))
        data = mujoco.MjData(model)
        mujoco.mj_resetDataKeyframe(model, data, model.key("piano_ready").id)
        mujoco.mj_forward(model, data)
        if pressed:
            # A fixed test torque, not a calibrated fingertip force: enough to reach the
            # key stop so the render shows dip, highlight colour and moving key sites.
            for note in pressed:
                data.qfrc_applied[model.joint(key_joint_name(note)).dofadr[0]] = 0.2
            for _ in range(round(0.3 / model.opt.timestep)):
                mujoco.mj_step(model, data)
            KeyHighlight(model).set_pressed(pressed)
        with mujoco.Renderer(model, height=960, width=1280) as renderer:
            renderer.update_scene(data, camera=arguments.camera)
            write_png(arguments.output, renderer.render())
    print(arguments.output.resolve())


if __name__ == "__main__":
    main()
