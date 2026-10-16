import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    piano_share = get_package_share_directory("rm_piano_player")
    bringup_share = get_package_share_directory("rm_bringup")
    piano_model = os.path.join(piano_share, "models", "piano_keyboard.sdf")
    piano_config = os.path.join(piano_share, "config", "piano.yaml")

    rm75_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_share, "launch", "rm_75_6fb_gazebo.launch.py")
        )
    )

    spawn_piano = Node(
        package="ros_gz_sim",
        executable="create",
        arguments=[
            "-world", "empty",
            "-file", piano_model,
            "-name", "piano_keyboard",
            "-x", "0.38225",
            "-y", "0.0",
            "-z", "0.30",
        ],
        output="screen",
    )

    piano_player = Node(
        package="rm_piano_player",
        executable="piano_player",
        name="piano_player",
        output="screen",
        parameters=[
            piano_config,
            {
                "execute": ParameterValue(
                    LaunchConfiguration("execute"), value_type=bool
                )
            },
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument("execute", default_value="false"),
        rm75_sim,
        TimerAction(period=6.0, actions=[spawn_piano]),
        TimerAction(period=8.0, actions=[piano_player]),
    ])
