"""Validate real launch descriptions without starting hardware processes."""

import importlib.util
from pathlib import Path

import pytest
from launch import LaunchContext
from launch.actions import GroupAction
from launch_ros.actions import Node


@pytest.mark.parametrize("use_rviz", ["true", "false"])
@pytest.mark.parametrize("debug", ["true", "false"])
def test_rviz_launch_conditions(use_rviz, debug):
    """RViz is optional and selects exactly one normal or debug process."""
    path = (Path(__file__).resolve().parents[1]
            / "launch/real_moveit_demo_6fb_v.launch.py")
    spec = importlib.util.spec_from_file_location("real_moveit_launch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    description = module.generate_launch_description()
    context = LaunchContext()
    context.launch_configurations.update(use_rviz=use_rviz, debug=debug)
    groups = [action for action in description.entities
              if isinstance(action, GroupAction)]
    assert len(groups) == 1
    group = groups[0]
    assert group.condition.evaluate(context) == (use_rviz == "true")
    nodes = [action for action in group.get_sub_entities()
             if isinstance(action, Node)]
    assert len(nodes) == 2
    enabled = [node for node in nodes if node.condition.evaluate(context)]
    assert len(enabled) == 1
    assert enabled[0] is nodes[1 if debug == "true" else 0]


def test_upright_mounts_match_state_publisher(monkeypatch):
    """MoveIt and TF must use the same upright base mounting transforms."""
    import xml.etree.ElementTree as ET

    config_dir = Path(__file__).resolve().parents[1]
    paths = {
        "moveit": config_dir / "launch/real_moveit_demo_6fb_v.launch.py",
        "bringup": config_dir.parent.parent
        / "rm_bringup/launch/rm_75_6fb_v_bringup.launch.py",
    }
    modules = {}
    for name, path in paths.items():
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[name] = module

    descriptions = {}

    def capture_moveit(description, config):
        descriptions["moveit"] = config.robot_description["robot_description"]
        return description

    def capture_node(**kwargs):
        if kwargs.get("package") == "robot_state_publisher":
            value = kwargs["parameters"][0]["robot_description"]
            descriptions["bringup"] = value.evaluate(LaunchContext())
        return Node(**kwargs)

    monkeypatch.setattr(modules["moveit"], "my_generate_move_group_launch",
                        capture_moveit)
    monkeypatch.setattr(modules["bringup"], "Node", capture_node)
    for module in modules.values():
        module.generate_launch_description()

    transforms = {}
    for name, xml in descriptions.items():
        robot = ET.fromstring(xml)
        transforms[name] = {}
        for side in ["left", "right"]:
            joint = robot.find(f"joint[@name='{side}_base_mount']")
            assert joint.attrib["type"] == "fixed"
            origin = joint.find("origin")
            rpy = [float(v) for v in origin.attrib["rpy"].split()]
            xyz = [float(v) for v in origin.attrib["xyz"].split()]
            assert rpy == pytest.approx([0.0, 0.0, 0.0])
            transforms[name][side] = (xyz, rpy)
    assert transforms["moveit"] == transforms["bringup"]
    left_xyz = transforms["moveit"]["left"][0]
    right_xyz = transforms["moveit"]["right"][0]
    assert right_xyz[0] == pytest.approx(left_xyz[0])
    assert right_xyz[2] == pytest.approx(left_xyz[2])
    assert right_xyz[1] - left_xyz[1] == pytest.approx(0.70)
