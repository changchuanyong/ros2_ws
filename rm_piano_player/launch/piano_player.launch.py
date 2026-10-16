from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config_file = PathJoinSubstitution([
        FindPackageShare("rm_piano_player"),
        "config",
        "piano.yaml",
    ])

    return LaunchDescription([
        DeclareLaunchArgument("execute", default_value="false"),
        Node(
            package="rm_piano_player",
            executable="piano_player",
            name="piano_player",
            output="screen",
            parameters=[
                config_file,
                {
                    "execute": ParameterValue(
                        LaunchConfiguration("execute"), value_type=bool
                    ),
                },
            ],
        ),
    ])
