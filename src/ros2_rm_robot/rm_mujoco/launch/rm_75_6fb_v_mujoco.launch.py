import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    package_share = get_package_share_directory("rm_mujoco")
    description_file = os.path.join(
        package_share, "config", "rm_75_6fb_v_mujoco.urdf.xacro"
    )
    controller_file = os.path.join(
        package_share, "config", "rm_75_6fb_v_mujoco_controllers.yaml"
    )
    robot_description = ParameterValue(
        Command(["xacro ", description_file, " headless:=", LaunchConfiguration("headless")]),
        value_type=str,
    )

    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[{"robot_description": robot_description, "use_sim_time": True}],
    )

    mujoco_control = Node(
        package="mujoco_ros2_control",
        executable="ros2_control_node",
        output="screen",
        parameters=[
            {"robot_description": robot_description, "use_sim_time": True},
            controller_file,
        ],
    )

    controller_spawners = TimerAction(
        period=2.0,
        actions=[
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=["joint_state_broadcaster", "--controller-manager", "/controller_manager"],
                output="screen",
            ),
            Node(
                package="controller_manager",
                executable="spawner",
                arguments=["rm_group_controller", "--controller-manager", "/controller_manager"],
                output="screen",
            ),
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "headless",
                default_value="false",
                description="Run MuJoCo without opening a Simulate window",
            ),
            robot_state_publisher,
            mujoco_control,
            controller_spawners,
        ]
    )
