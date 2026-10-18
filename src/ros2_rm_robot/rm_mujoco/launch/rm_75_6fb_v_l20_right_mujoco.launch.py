import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import TimerAction
from launch.substitutions import Command
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    package_share = get_package_share_directory("rm_mujoco")
    description_file = os.path.join(
        package_share, "config", "rm_75_6fb_v_l20_right_mujoco.urdf.xacro"
    )
    controller_file = os.path.join(
        package_share, "config", "rm_75_6fb_v_l20_right_mujoco_controllers.yaml"
    )
    robot_description = ParameterValue(
        Command(["xacro ", description_file]), value_type=str
    )

    return LaunchDescription(
        [
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
                    {"robot_description": robot_description, "use_sim_time": True},
                    controller_file,
                ],
            ),
            TimerAction(
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
                    Node(
                        package="controller_manager",
                        executable="spawner",
                        arguments=["l20_hand_controller", "--controller-manager", "/controller_manager"],
                        output="screen",
                    ),
                ],
            ),
            Node(
                package="rm_mujoco",
                executable="l20_right_command_bridge.py",
                output="screen",
            ),
        ]
    )
