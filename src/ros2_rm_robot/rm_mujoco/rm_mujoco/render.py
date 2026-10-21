"""Render the actual MuJoCo piano scene without starting ROS or hardware."""

import argparse
from pathlib import Path
import struct
import tempfile
import zlib

from ament_index_python.packages import get_package_share_directory
import mujoco
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
    parser.add_argument("--camera", default="overview", choices=("overview", "front"))
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    layout = load_layout(arguments.scene_config)
    with tempfile.TemporaryDirectory(prefix="rm75_render_") as directory:
        model_path = build_model(
            share / "models/rm_75_6fb_v_dual_l20.xml", layout, directory
        )
        model = mujoco.MjModel.from_xml_path(str(model_path))
        data = mujoco.MjData(model)
        mujoco.mj_resetDataKeyframe(model, data, model.key("piano_ready").id)
        mujoco.mj_forward(model, data)
        with mujoco.Renderer(model, height=960, width=1280) as renderer:
            renderer.update_scene(data, camera=arguments.camera)
            write_png(arguments.output, renderer.render())
    print(arguments.output.resolve())


if __name__ == "__main__":
    main()
