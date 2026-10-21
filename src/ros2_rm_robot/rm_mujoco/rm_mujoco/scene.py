"""Generate the same approximate table/piano layout for MuJoCo and MoveIt.

The dimensions are an editable visual approximation of the reference photo.
Keys are fixed geometry in this phase; they do not produce MIDI/contact events.
"""

import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zlib

import yaml


WHITE_CLASSES = frozenset((0, 2, 4, 5, 7, 9, 11))
COLORS = {
    "scene_oak": (0.70, 0.47, 0.24, 1.0),
    "scene_piano_wood": (0.60, 0.36, 0.17, 1.0),
    "scene_metal": (0.26, 0.28, 0.29, 1.0),
    "scene_silver": (0.62, 0.65, 0.67, 1.0),
    "scene_ivory": (0.95, 0.94, 0.89, 1.0),
    "scene_black": (0.025, 0.028, 0.032, 1.0),
    "scene_floor": (0.44, 0.46, 0.46, 1.0),
    "scene_wall": (0.77, 0.78, 0.75, 1.0),
    "scene_glass": (0.48, 0.68, 0.78, 1.0),
    "scene_brass": (0.68, 0.56, 0.27, 1.0),
}


def _numbers(values):
    return " ".join(f"{value:.9g}" for value in values)


def load_layout(path):
    """Load the shared YAML layout, rejecting invalid geometry dimensions."""
    with Path(path).open(encoding="utf-8") as stream:
        layout = yaml.safe_load(stream)
    for name in ("table", "bases", "piano_frame", "keyboard", "piano", "cameras"):
        if not isinstance(layout.get(name), dict):
            raise ValueError(f"Missing scene mapping: {name}")
    vectors = [layout["table"]["position"], layout["table"]["size"],
               layout["piano_frame"]["position"]]
    for side in ("left", "right"):
        vectors.extend((layout["bases"][side]["position"], layout["bases"][side]["rpy"]))
    for vector in vectors:
        if len(vector) != 3 or not all(math.isfinite(float(value)) for value in vector):
            raise ValueError("Scene vectors must contain three finite values")
    dimensions = list(layout["table"]["size"]) + list(layout["keyboard"].values())
    dimensions += [layout["piano"]["width"], layout["piano"]["depth"]]
    if not all(math.isfinite(float(value)) and value > 0 for value in dimensions):
        raise ValueError("Scene dimensions must be finite and positive")
    keys = layout["keyboard"]
    if keys["black_width"] + keys["gap"] >= keys["white_pitch"]:
        raise ValueError("Black keys must be narrower than a white-key pitch")
    if keys["black_depth"] >= keys["white_depth"]:
        raise ValueError("Black keys must be shorter than white keys")
    if layout["piano"]["width"] <= 52 * keys["white_pitch"] + 0.06:
        raise ValueError("Piano case is too narrow for 52 white keys")
    return layout


def key_positions(layout):
    """Return 88 piano_frame-local press points, indexed by MIDI note minus 21."""
    keyboard = layout["keyboard"]
    pitch = keyboard["white_pitch"]
    white_index = 0
    positions = []
    for note in range(21, 109):
        if note % 12 in WHITE_CLASSES:
            positions.append([(white_index - 25.5) * pitch,
                              (keyboard["white_depth"] - keyboard["black_depth"]) * 0.65,
                              0.0])
            white_index += 1
        else:
            positions.append([(white_index - 26) * pitch,
                              keyboard["white_depth"] - keyboard["black_depth"] * 0.5,
                              keyboard["black_height"]])
    return positions


def _box(name, position, size, material, collision=True, rpy=None):
    return {"name": name, "position": position, "size": size, "material": material,
            "collision": collision, "rpy": rpy or [0.0, 0.0, 0.0]}


def environment_geometry(layout):
    """Return shared world-frame boxes, including split white-key geometry."""
    parts = []
    table = layout["table"]
    tx, ty, tz = table["position"]
    sx, sy, sz = table["size"]
    parts.append(_box("table_top", [tx, ty, tz], [sx, sy, sz], "scene_oak"))
    leg_height = tz - sz * 0.5
    for ix, sign_x in enumerate((-1, 1)):
        for iy, sign_y in enumerate((-1, 1)):
            parts.append(_box(f"table_leg_{ix}_{iy}",
                              [tx + sign_x * (sx / 2 - 0.075),
                               ty + sign_y * (sy / 2 - 0.075), leg_height / 2],
                              [0.055, 0.055, leg_height], "scene_metal"))
    for side in ("left", "right"):
        x, y, z = layout["bases"][side]["position"]
        parts.append(_box(f"{side}_mounting_plate", [x, y, z - 0.005],
                          [0.20, 0.20, 0.01], "scene_silver", False))
        for index, (dx, dy) in enumerate(((-0.082, -0.082), (-0.082, 0.082),
                                        (0.082, -0.082), (0.082, 0.082))):
            parts.append(_box(f"{side}_mounting_bolt_{index}", [x + dx, y + dy, z + 0.001],
                              [0.012, 0.012, 0.003], "scene_black", False))

    px, py, pz = layout["piano_frame"]["position"]
    width, depth = layout["piano"]["width"], layout["piano"]["depth"]

    def piano_box(name, position, size, material="scene_piano_wood", collision=True,
                  rpy=None):
        world = [position[0] + px, position[1] + py, position[2] + pz]
        parts.append(_box(name, world, size, material, collision, rpy))

    inner_width = width - 0.072
    piano_box("piano_keybed", [0, 0.070, -0.028], [inner_width, 0.22, 0.032], "scene_black")
    piano_box("piano_front_rail", [0, -0.032, -0.049], [inner_width, 0.018, 0.065])
    piano_box("piano_rear_deck", [0, (0.15 + depth - 0.04) / 2, 0.020],
              [inner_width, depth - 0.19, 0.044])
    piano_box("piano_back_rail", [0, depth - 0.048, -0.025], [inner_width, 0.016, 0.13])
    for side, sign in (("left", -1), ("right", 1)):
        piano_box(f"piano_{side}_side", [sign * (width / 2 - 0.018), depth / 2 - 0.04,
                                        0.025 - pz / 2],
                  [0.036, depth, pz + 0.05])
        piano_box(f"piano_{side}_foot", [sign * (width / 2 - 0.028), depth / 2 - 0.04,
                                        0.025 - pz], [0.075, depth + 0.08, 0.05])
    piano_box("piano_lower_crossbar", [0, depth - 0.075, 0.12 - pz],
              [width - 0.072, 0.045, 0.15])
    piano_box("piano_pedal_board", [0, 0.20, 0.045 - pz], [0.40, 0.16, 0.04])
    for index, x in enumerate((-0.055, 0.0, 0.055)):
        piano_box(f"piano_pedal_{index}", [x, 0.115, 0.078 - pz],
                  [0.022, 0.10, 0.012], "scene_brass")
    piano_box("piano_music_rest", [0, 0.29, 0.16], [0.48, 0.012, 0.22],
              "scene_piano_wood", True, [-0.16, 0, 0])
    piano_box("piano_music_ledge", [0, 0.255, 0.06], [0.50, 0.05, 0.015])
    piano_box("piano_control_panel", [-width / 2 + 0.16, 0.22, 0.044],
              [0.17, 0.055, 0.006], "scene_black", False)

    keys = layout["keyboard"]
    pitch, gap = keys["white_pitch"], keys["gap"]
    front_depth = keys["white_depth"] - keys["black_depth"]
    white_index = 0
    for note, point in zip(range(21, 109), key_positions(layout)):
        if note % 12 not in WHITE_CLASSES:
            piano_box(f"piano_key_{note:03d}",
                      [point[0], point[1], keys["black_height"] - keys["white_thickness"] / 2],
                      [keys["black_width"], keys["black_depth"] - gap,
                       keys["white_thickness"]], "scene_black")
            continue
        x = (white_index - 25.5) * pitch
        white_index += 1
        piano_box(f"piano_key_{note:03d}", [x, front_depth / 2, -keys["white_thickness"] / 2],
                  [pitch - gap, front_depth - gap, keys["white_thickness"]], "scene_ivory")
        left = x - (pitch - gap) / 2
        right = x + (pitch - gap) / 2
        if note > 21 and (note - 1) % 12 not in WHITE_CLASSES:
            left += keys["black_width"] / 2
        if note < 108 and (note + 1) % 12 not in WHITE_CLASSES:
            right -= keys["black_width"] / 2
        piano_box(f"piano_key_{note:03d}_rear",
                  [(left + right) / 2, front_depth + keys["black_depth"] / 2,
                   -keys["white_thickness"] / 2],
                  [right - left, keys["black_depth"] - gap, keys["white_thickness"]],
                  "scene_ivory")

    if layout.get("background", {}).get("enabled", True):
        parts.append(_box("lab_back_wall", [0, 2.05, 1.6], [5.5, 0.08, 3.2], "scene_wall"))
        parts.append(_box("lab_window", [-0.7, 1.99, 1.85], [3.8, 0.025, 2.25],
                          "scene_glass", False))
        for index in range(6):
            parts.append(_box(f"window_post_{index}", [-2.6 + index * 0.76, 1.96, 1.85],
                              [0.045, 0.05, 2.35], "scene_metal", False))
        for index, height in enumerate((0.70, 1.33, 3.00)):
            parts.append(_box(f"window_rail_{index}", [-0.7, 1.96, height],
                              [3.85, 0.05, 0.045], "scene_metal", False))
        parts.append(_box("lab_counter", [0.4, 1.45, 0.91], [2.6, 0.65, 0.045], "scene_oak"))
        parts.append(_box("lab_cabinet", [0.4, 1.45, 0.45], [2.55, 0.59, 0.90], "scene_wall"))
        for index, x in enumerate((-0.43, 0.42, 1.27)):
            parts.append(_box(f"cabinet_door_{index}", [x, 1.145, 0.47],
                              [0.82, 0.02, 0.82], "scene_oak", False))
            parts.append(_box(f"cabinet_handle_{index}", [x + 0.29, 1.125, 0.68],
                              [0.015, 0.025, 0.13], "scene_silver", False))
    return parts


def _wood_texture(path):
    """Write a deterministic PNG using only the Python standard library."""
    width = height = 256
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            grain = math.sin(x * 0.22 + 1.8 * math.sin(y * 0.018))
            fine = math.sin(x * 1.71 + math.sin(y * 0.07))
            value = 0.92 + 0.06 * grain + 0.02 * fine
            raw.extend(int(channel * value) for channel in (220, 169, 107))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    content = b"\x89PNG\r\n\x1a\n"
    content += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    content += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.write_bytes(content)


def _camera_axes(position, target):
    z_axis = [position[index] - target[index] for index in range(3)]
    norm = math.sqrt(sum(value * value for value in z_axis))
    z_axis = [value / norm for value in z_axis]
    x_axis = [-z_axis[1], z_axis[0], 0.0]
    norm = math.sqrt(sum(value * value for value in x_axis))
    if norm < 1e-9:
        raise ValueError("Scene cameras must not look straight along the vertical axis")
    x_axis = [value / norm for value in x_axis]
    y_axis = [z_axis[1] * x_axis[2] - z_axis[2] * x_axis[1],
              z_axis[2] * x_axis[0] - z_axis[0] * x_axis[2],
              z_axis[0] * x_axis[1] - z_axis[1] * x_axis[0]]
    return x_axis + y_axis


def build_model(template_path, layout, output_dir):
    """Generate an MJCF beside its texture, preserving source robot dynamics."""
    template_path = Path(template_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    root = ET.parse(template_path).getroot()
    compiler = root.find("compiler")
    compiler.set("meshdir", str((template_path.parent / compiler.get("meshdir", ".")).resolve()))
    asset = root.find("asset")
    _wood_texture(output_dir / "oak.png")
    ET.SubElement(asset, "texture", name="scene_wood_texture", type="2d",
                  file=str(output_dir / "oak.png"))
    ET.SubElement(asset, "texture", name="scene_sky", type="skybox", builtin="gradient",
                  rgb1="0.66 0.77 0.85", rgb2="0.91 0.93 0.94", width="256", height="1536")
    for name, color in COLORS.items():
        attributes = {"name": name, "rgba": _numbers(color), "specular": "0.18", "shininess": "0.2"}
        if name in ("scene_oak", "scene_piano_wood"):
            attributes.update(texture="scene_wood_texture", texrepeat="1 3", texuniform="true",
                              rgba="1 1 1 1" if name == "scene_oak" else "0.88 0.78 0.68 1")
        if name == "scene_glass":
            attributes["emission"] = "0.35"
        ET.SubElement(asset, "material", **attributes)
    world = root.find("worldbody")
    for child in list(world):
        if (child.tag == "include" and child.get("file") == "piano_keyboard.xml"
                or child.tag == "geom" and child.get("name") == "floor"
                or child.tag == "body" and child.get("name") == "piano_keyboard"
                or child.tag in ("light", "camera")):
            world.remove(child)
    ET.SubElement(world, "geom", name="floor", type="plane", size="5 5 0.1",
                  material="scene_floor", friction="0.8 0.01 0.001")
    for name, position, diffuse in (("key", "-1 -2 3.5", "0.50 0.48 0.45"),
                                    ("fill", "2 0.5 3", "0.18 0.20 0.23")):
        ET.SubElement(world, "light", name=name, pos=position, dir="0 0 -1",
                      diffuse=diffuse, ambient="0.03 0.03 0.03", directional="true",
                      castshadow="true" if name == "key" else "false")
    for name, camera in layout["cameras"].items():
        ET.SubElement(world, "camera", name=name, pos=_numbers(camera["position"]),
                      xyaxes=_numbers(_camera_axes(camera["position"], camera["target"])),
                      fovy=str(camera["fovy"]))
    for side in ("left", "right"):
        base = world.find(f"body[@name='{side}_base_link']")
        # Position-controlled robot servos compensate gravity while holding a pose.
        # Without this, the photo's bent arms sag several degrees under the hand load.
        for body in base.iter("body"):
            body.set("gravcomp", "1")
        base.set("pos", _numbers(layout["bases"][side]["position"]))
        # MuJoCo's lowercase xyz Euler convention differs from URDF fixed-axis RPY.
        base.attrib.pop("euler", None)
        roll, pitch, yaw = (value / 2 for value in layout["bases"][side]["rpy"])
        cr, sr, cp, sp, cy, sy = (math.cos(roll), math.sin(roll), math.cos(pitch),
                                 math.sin(pitch), math.cos(yaw), math.sin(yaw))
        base.set("quat", _numbers([cr * cp * cy + sr * sp * sy,
                                    sr * cp * cy - cr * sp * sy,
                                    cr * sp * cy + sr * cp * sy,
                                    cr * cp * sy - sr * sp * cy]))
    environment = ET.SubElement(world, "body", name="piano_environment")
    ET.SubElement(environment, "site", name="piano_frame", type="sphere", size="0.002",
                  pos=_numbers(layout["piano_frame"]["position"]), rgba="0 0 0 0")
    for part in environment_geometry(layout):
        ET.SubElement(environment, "geom", name=part["name"], type="box",
                      pos=_numbers(part["position"]), size=_numbers(value / 2 for value in part["size"]),
                      euler=_numbers(part["rpy"]), material=part["material"],
                      contype="1" if part["collision"] else "0",
                      conaffinity="1" if part["collision"] else "0")
    visual = root.find("visual")
    headlight = visual.find("headlight")
    headlight.set("diffuse", "0.35 0.35 0.35")
    headlight.set("ambient", "0.15 0.15 0.15")
    headlight.set("specular", "0.08 0.08 0.08")
    overview = layout["cameras"]["overview"]
    delta = [overview["position"][index] - overview["target"][index] for index in range(3)]
    global_view = visual.find("global")
    if global_view is None:
        global_view = ET.SubElement(visual, "global")
    global_view.set("azimuth", str(math.degrees(math.atan2(-delta[1], -delta[0]))))
    global_view.set("elevation", str(-math.degrees(math.atan2(delta[2], math.hypot(*delta[:2])))))
    global_view.set("fovy", str(overview["fovy"]))
    statistic = root.find("statistic")
    if statistic is None:
        statistic = ET.SubElement(root, "statistic")
    statistic.set("center", _numbers(overview["target"]))
    # MuJoCo's default free-camera distance is 1.5 times this extent.
    statistic.set("extent", str(math.sqrt(sum(value * value for value in delta)) / 1.5))
    quality = visual.find("quality")
    if quality is None:
        quality = ET.SubElement(visual, "quality")
    quality.set("shadowsize", "4096")
    initial = layout.get("initial_positions", {})
    if initial:
        keyframes = root.find("keyframe")
        if keyframes is None:
            keyframes = ET.SubElement(root, "keyframe")
        previous = keyframes.find("key[@name='piano_ready']")
        if previous is not None:
            keyframes.remove(previous)
        qpos = [initial.get(joint.get("name"), 0.0) for joint in world.iter("joint")]
        ctrl = [initial.get(actuator.get("joint"), 0.0) for actuator in root.find("actuator")]
        ET.SubElement(keyframes, "key", name="piano_ready", qpos=_numbers(qpos), ctrl=_numbers(ctrl))
    ET.indent(root, space="  ")
    output = output_dir / "rm_75_dual_l20_piano_scene.xml"
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    return output


def add_environment_to_urdf(robot_xml, layout):
    """Attach the matching scene to base_root for RViz and MoveIt collisions."""
    root = ET.fromstring(robot_xml)
    if root.find("link[@name='base_root']") is None:
        raise ValueError("The robot URDF must contain base_root")
    if root.find("link[@name='piano_environment']") is not None:
        raise ValueError("The robot URDF already contains the piano environment")
    scene = ET.SubElement(root, "link", name="piano_environment")
    joint = ET.SubElement(root, "joint", name="piano_environment_fixed", type="fixed")
    ET.SubElement(joint, "parent", link="base_root")
    ET.SubElement(joint, "child", link="piano_environment")
    ET.SubElement(joint, "origin", xyz="0 0 0", rpy="0 0 0")
    for part in environment_geometry(layout):
        for kind in ("visual", "collision") if part["collision"] else ("visual",):
            element = ET.SubElement(scene, kind, name=part["name"])
            ET.SubElement(element, "origin", xyz=_numbers(part["position"]), rpy=_numbers(part["rpy"]))
            geometry = ET.SubElement(element, "geometry")
            ET.SubElement(geometry, "box", size=_numbers(part["size"]))
            if kind == "visual":
                material = ET.SubElement(element, "material", name=part["material"])
                ET.SubElement(material, "color", rgba=_numbers(COLORS[part["material"]]))
    if root.find("link[@name='piano_frame']") is None:
        ET.SubElement(root, "link", name="piano_frame")
        joint = ET.SubElement(root, "joint", name="piano_frame_fixed", type="fixed")
        ET.SubElement(joint, "parent", link="base_root")
        ET.SubElement(joint, "child", link="piano_frame")
        ET.SubElement(joint, "origin", xyz=_numbers(layout["piano_frame"]["position"]), rpy="0 0 0")
    return ET.tostring(root, encoding="unicode")
