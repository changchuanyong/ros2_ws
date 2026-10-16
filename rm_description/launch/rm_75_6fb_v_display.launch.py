import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch.substitutions import Command, FindExecutable


def generate_launch_description():
    urdf_file = os.path.join(
        get_package_share_directory("rm_description"),
        "urdf",
        "rm_75_6fb_v.urdf",
    )
    robot_description = Command([
        FindExecutable(name="xacro"),
        " ",
        urdf_file,
    ])

    return LaunchDescription([
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            parameters=[{
                "robot_description": ParameterValue(robot_description, value_type=str)
            }],
            output="screen",
        )
    ])
