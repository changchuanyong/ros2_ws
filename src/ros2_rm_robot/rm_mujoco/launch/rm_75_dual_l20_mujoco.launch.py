import os
import tempfile
import xml.etree.ElementTree as ET

import xacro

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, RegisterEventHandler, TimerAction
from launch.conditions import IfCondition
from launch.event_handlers import OnShutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from moveit_configs_utils import MoveItConfigsBuilder
from rm_mujoco.scene import add_environment_to_urdf, build_model, load_layout


def build_moveit_config(layout):
    description_path = os.path.join(
        get_package_share_directory("rm_description"),
        "urdf",
        "rm_75_6fb_v_dual.urdf.xacro",
    )
    mappings = {
        f"{side}_{kind}": " ".join(str(v) for v in layout["bases"][side][field])
        for side in ("left", "right")
        for kind, field in (("xyz", "position"), ("rpy", "rpy"))
    }
    mappings["piano_xyz"] = " ".join(str(v) for v in layout["piano_frame"]["position"])
    config = (
        MoveItConfigsBuilder("rm_75_6fb_v_dual", package_name="rm_75_config")
        .robot_description(
            file_path=description_path,
            mappings=mappings,
        )
        .robot_description_semantic(file_path="config/rm_75_6fb_v_dual_description.srdf")
        .robot_description_kinematics(file_path="config/kinematics_dual.yaml")
        .trajectory_execution(
            file_path="config/moveit_controllers_dual_gazebo.yaml",
            moveit_manage_controllers=False,
        )
        .planning_pipelines(
            default_planning_pipeline="ompl",
            pipelines=["ompl", "pilz_industrial_motion_planner"],
            load_all=False,
        )
        .pilz_cartesian_limits(file_path="config/pilz_cartesian_limits.yaml")
        .joint_limits(file_path="config/joint_limits_dual.yaml")
        .to_moveit_configs()
    )
    config.robot_description["robot_description"] = add_environment_to_urdf(
        config.robot_description["robot_description"], layout
    )
    semantic = ET.fromstring(config.robot_description_semantic["robot_description_semantic"])
    for group, sides in (("left_arm", ("left",)), ("right_arm", ("right",)),
                         ("dual_arms", ("left", "right"))):
        state = ET.SubElement(semantic, "group_state", name="piano_ready", group=group)
        for side in sides:
            for index in range(1, 8):
                name = f"{side}_joint{index}"
                ET.SubElement(state, "joint", name=name,
                              value=str(layout["initial_positions"][name]))
    config.robot_description_semantic["robot_description_semantic"] = ET.tostring(
        semantic, encoding="unicode"
    )
    return config


def launch_setup(context):
    package_share = get_package_share_directory("rm_mujoco")
    scene_config = LaunchConfiguration("scene_config").perform(context)
    layout = load_layout(scene_config)
    scene_directory = tempfile.TemporaryDirectory(prefix="rm75_piano_")
    model_path = build_model(
        os.path.join(package_share, "models", "rm_75_6fb_v_dual_l20.xml"),
        layout, scene_directory.name,
    )
    control_file = os.path.join(
        package_share, "config", "rm_75_6fb_v_dual_l20_mujoco_control.urdf.xacro"
    )
    controller_file = os.path.join(
        package_share, "config", "rm_75_6fb_v_dual_l20_mujoco_controllers.yaml"
    )

    mujoco_description = ParameterValue(
        xacro.process_file(control_file, mappings={
            "headless": LaunchConfiguration("headless").perform(context),
            "mujoco_model": str(model_path),
            "scene_config": scene_config,
        }).toxml(),
        value_type=str,
    )
    moveit_config = build_moveit_config(layout)
    robot_description = ParameterValue(
        moveit_config.robot_description["robot_description"], value_type=str
    )

    move_group_configuration = {
        "publish_robot_description_semantic": True,
        "allow_trajectory_execution": True,
        "publish_planning_scene": True,
        "publish_geometry_updates": True,
        "publish_state_updates": True,
        "publish_transforms_updates": True,
        "monitor_dynamics": False,
    }

    return [
        RegisterEventHandler(OnShutdown(on_shutdown=[OpaqueFunction(
            function=lambda context: scene_directory.cleanup()
        )])),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            output="screen",
            parameters=[{"robot_description": robot_description, "use_sim_time": True}],
        ),
        Node(
            package="mujoco_ros2_control",
            executable="ros2_control_node",
            output="screen",
            parameters=[
                {"robot_description": mujoco_description, "use_sim_time": True},
                controller_file,
            ],
        ),
        TimerAction(
            period=2.0,
            actions=[
                Node(
                    package="controller_manager",
                    executable="spawner",
                    arguments=[controller, "--controller-manager", "/controller_manager"],
                    output="screen",
                )
                for controller in [
                    "joint_state_broadcaster",
                    "left_arm_controller",
                    "right_arm_controller",
                    "left_l20_hand_controller",
                    "right_l20_hand_controller",
                ]
            ],
        ),
        Node(
            package="rm_mujoco",
            executable="l20_dual_command_bridge.py",
            output="screen",
        ),
        Node(
            package="moveit_ros_move_group",
            executable="move_group",
            output="screen",
            parameters=[
                moveit_config.to_dict(),
                move_group_configuration,
                {"use_sim_time": True},
            ],
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            name="rviz2",
            arguments=[
                "-d",
                os.path.join(
                    get_package_share_directory("rm_75_config"),
                    "config",
                    "moveit.rviz",
                ),
            ],
            parameters=[
                moveit_config.robot_description,
                moveit_config.robot_description_semantic,
                moveit_config.planning_pipelines,
                moveit_config.robot_description_kinematics,
                moveit_config.joint_limits,
                {"use_sim_time": True},
            ],
            condition=IfCondition(LaunchConfiguration("use_rviz")),
            output="screen",
        ),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("headless", default_value="false"),
        DeclareLaunchArgument("use_rviz", default_value="true"),
        DeclareLaunchArgument("scene_config", default_value=os.path.join(
            get_package_share_directory("rm_mujoco"), "config", "piano_scene.yaml"
        )),
        OpaqueFunction(function=launch_setup),
    ])
