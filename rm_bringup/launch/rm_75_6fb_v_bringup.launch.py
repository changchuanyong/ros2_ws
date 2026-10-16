import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    rm_driver = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("rm_driver"),
                "launch",
                "rm_75_driver.launch.py",
            )
        )
    )
    rm_description = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("rm_description"),
                "launch",
                "rm_75_6fb_v_display.launch.py",
            )
        )
    )
    rm_control = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("rm_control"),
                "launch",
                "rm_75_control.launch.py",
            )
        )
    )
    rm_moveit_config = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("rm_75_config"),
                "launch",
                "real_moveit_demo_6fb_v.launch.py",
            )
        )
    )

    return LaunchDescription([
        rm_driver,
        rm_description,
        rm_control,
        rm_moveit_config,
    ])
