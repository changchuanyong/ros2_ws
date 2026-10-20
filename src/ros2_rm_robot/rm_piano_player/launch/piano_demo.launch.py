import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    piano_share = get_package_share_directory("rm_piano_player")
    piano = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(piano_share, "launch", "rm_75_dual_l20_piano_mujoco.launch.py")
        ),
        launch_arguments={
            "midi_file": LaunchConfiguration("midi_file"),
            "execute": LaunchConfiguration("execute"),
            "headless": LaunchConfiguration("headless"),
            "use_rviz": LaunchConfiguration("use_rviz"),
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument("midi_file", default_value=""),
        DeclareLaunchArgument("execute", default_value="false"),
        DeclareLaunchArgument("headless", default_value="false"),
        DeclareLaunchArgument("use_rviz", default_value="true"),
        piano,
    ])
