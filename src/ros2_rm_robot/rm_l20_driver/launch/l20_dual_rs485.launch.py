from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument("left_hand_port", default_value="/dev/ttyUSB0"),
        DeclareLaunchArgument("right_hand_port", default_value="/dev/ttyUSB1"),
        DeclareLaunchArgument("hand_joint", default_value="L20-11"),
        DeclareLaunchArgument("baudrate", default_value="115200"),
        DeclareLaunchArgument("slave_id", default_value="1"),
        DeclareLaunchArgument("poll_rate", default_value="20.0"),
    ]
    nodes = [
        Node(
            package="rm_l20_driver",
            executable="l20_rs485_driver",
            name=f"{side}_l20_driver",
            output="screen",
            parameters=[{
                "hand_type": side,
                "hand_joint": LaunchConfiguration("hand_joint"),
                "modbus": LaunchConfiguration(f"{side}_hand_port"),
                "baudrate": ParameterValue(LaunchConfiguration("baudrate"), value_type=int),
                "slave_id": ParameterValue(LaunchConfiguration("slave_id"), value_type=int),
                "poll_rate": ParameterValue(LaunchConfiguration("poll_rate"), value_type=float),
            }],
        )
        for side in ("left", "right")
    ]
    return LaunchDescription(arguments + nodes)
