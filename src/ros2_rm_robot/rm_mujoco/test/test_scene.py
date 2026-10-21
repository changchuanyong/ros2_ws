"""Check keyboard topology and matching MuJoCo/MoveIt scene geometry."""

from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.scene import (  # noqa: E402
    add_environment_to_urdf, build_model, environment_geometry, key_positions, load_layout,
)


@pytest.fixture
def layout():
    return load_layout(PACKAGE / "config" / "piano_scene.yaml")


def test_full_keyboard_uses_white_spacing_and_black_boundaries(layout):
    points = key_positions(layout)
    assert len(points) == 88
    assert sum(point[2] == 0 for point in points) == 52
    assert sum(point[2] > 0 for point in points) == 36
    assert all(a[0] < b[0] for a, b in zip(points, points[1:]))
    pitch = layout["keyboard"]["white_pitch"]
    assert points[0][0] == pytest.approx(-25.5 * pitch)
    assert points[-1][0] == pytest.approx(25.5 * pitch)
    # B/C and E/F have no black key between them.
    assert points[24 - 21][0] - points[23 - 21][0] == pytest.approx(pitch)
    assert points[29 - 21][0] - points[28 - 21][0] == pytest.approx(pitch)
    assert points[22 - 21][0] == pytest.approx((points[0][0] + points[2][0]) / 2)


def test_black_keys_form_two_then_three_in_each_complete_octave(layout):
    points = key_positions(layout)
    # C through B: C#/D# and F#/G#/A#, repeated across the seven full octaves.
    expected = [False, True, False, True, False, False,
                True, False, True, False, True, False]
    for c_note in range(24, 97, 12):
        octave = points[c_note - 21:c_note - 21 + 12]
        assert [point[2] > 0 for point in octave] == expected


@pytest.mark.parametrize("translated", [False, True])
def test_press_points_match_the_generated_key_surfaces(layout, tmp_path, translated):
    if translated:
        layout["piano_frame"]["position"] = [0.17, 0.24, 0.82]
        layout["keyboard"]["white_pitch"] = 0.024
        layout["keyboard"]["white_depth"] = 0.17
        layout["keyboard"]["black_height"] = 0.014
    output = build_model(PACKAGE / "models" / "rm_75_6fb_v_dual_l20.xml", layout, tmp_path)
    mjcf = ET.parse(output).getroot()
    frame = layout["piano_frame"]["position"]
    for note, point in enumerate(key_positions(layout), start=21):
        geom = mjcf.find(f".//geom[@name='piano_key_{note:03d}']")
        assert geom is not None
        center = [float(value) for value in geom.get("pos").split()]
        half_size = [float(value) for value in geom.get("size").split()]
        target = [origin + offset for origin, offset in zip(frame, point)]
        assert target[2] == pytest.approx(center[2] + half_size[2])
        for axis in (0, 1):
            assert center[axis] - half_size[axis] < target[axis] < center[axis] + half_size[axis]


def test_key_solids_do_not_overlap(layout):
    keys = [part for part in environment_geometry(layout) if part["name"].startswith("piano_key_")]
    assert len(keys) == 140  # 52 split whites and 36 blacks.
    for index, first in enumerate(keys):
        for second in keys[index + 1:]:
            overlap = [abs(a - b) < (sa + sb) / 2 - 1e-9
                       for a, b, sa, sb in zip(first["position"], second["position"],
                                              first["size"], second["size"])]
            assert not all(overlap), (first["name"], second["name"])
            # Raised black keys must fit between the white-key rear sections,
            # rather than hide overlapping rectangles at a different height.
            assert not all(overlap[:2]), (first["name"], second["name"])


def test_table_mounts_and_piano_have_clearance(layout):
    table = layout["table"]
    table_front = table["position"][1] + table["size"][1] / 2
    assert table_front < layout["piano_frame"]["position"][1] - 0.04
    table_top = table["position"][2] + table["size"][2] / 2
    for base in layout["bases"].values():
        assert base["position"][2] == pytest.approx(table_top + 0.01)
        assert base["position"][1] + 0.1 <= table_front + 1e-9


def test_urdf_and_mjcf_use_same_geometry(layout, tmp_path):
    output = build_model(PACKAGE / "models" / "rm_75_6fb_v_dual_l20.xml", layout, tmp_path)
    mjcf = ET.parse(output).getroot()
    urdf = ET.fromstring(add_environment_to_urdf('<robot name="test"><link name="base_root"/></robot>', layout))
    for part in environment_geometry(layout):
        geom = mjcf.find(f".//geom[@name='{part['name']}']")
        visual = urdf.find(f".//visual[@name='{part['name']}']")
        assert geom is not None and visual is not None
        assert [float(x) for x in geom.get("pos").split()] == pytest.approx(part["position"])
        assert visual.find("origin").get("xyz") == geom.get("pos")
        assert [float(x) * 2 for x in geom.get("size").split()] == pytest.approx(part["size"])
        assert [float(x) for x in visual.find("geometry/box").get("size").split()] == pytest.approx(part["size"])
        assert visual.find("origin").get("rpy") == geom.get("euler")
        collision = urdf.find(f".//collision[@name='{part['name']}']")
        assert (collision is not None) == part["collision"]
        if collision is not None:
            assert collision.find("origin").attrib == visual.find("origin").attrib
            assert collision.find("geometry/box").attrib == visual.find("geometry/box").attrib
    for side in ("left", "right"):
        base = mjcf.find(f"worldbody/body[@name='{side}_base_link']")
        assert [float(x) for x in base.get("pos").split()] == pytest.approx(layout["bases"][side]["position"])
    piano_frame = urdf.find("joint[@name='piano_frame_fixed']/origin")
    assert [float(x) for x in piano_frame.get("xyz").split()] == pytest.approx(layout["piano_frame"]["position"])
    assert not mjcf.findall(".//include")
    assert (tmp_path / "oak.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    ready = mjcf.find("keyframe/key[@name='piano_ready']")
    assert len(ready.get("qpos").split()) == len(list(mjcf.find("worldbody").iter("joint")))
    assert len(ready.get("ctrl").split()) == len(mjcf.find("actuator"))


def test_invalid_keyboard_geometry_is_rejected(layout, tmp_path):
    import yaml
    layout["keyboard"]["black_width"] = 0.1
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(layout), encoding="utf-8")
    with pytest.raises(ValueError, match="narrower"):
        load_layout(path)
