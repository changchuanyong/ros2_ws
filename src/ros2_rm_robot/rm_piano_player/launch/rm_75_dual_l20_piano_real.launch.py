import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    bringup_share = get_package_share_directory("rm_bringup")
    player_share = get_package_share_directory("rm_piano_player")
    bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_share, "launch", "rm_75_6fb_v_bringup.launch.py")
        ),
        launch_arguments={
            "left_arm_ip": LaunchConfiguration("left_arm_ip"),
            "right_arm_ip": LaunchConfiguration("right_arm_ip"),
            "left_udp_ip": LaunchConfiguration("left_udp_ip"),
            "right_udp_ip": LaunchConfiguration("right_udp_ip"),
            "left_udp_port": LaunchConfiguration("left_udp_port"),
            "right_udp_port": LaunchConfiguration("right_udp_port"),
            "use_rviz": LaunchConfiguration("use_rviz"),
        }.items(),
    )
    left_hand = Node(
        package="linker_hand_ros2_sdk",
        executable="linker_hand_sdk",
        name="left_linker_hand_sdk",
        output="screen",
        parameters=[{
            "hand_type": "left",
            "hand_joint": LaunchConfiguration("hand_joint"),
            "is_touch": True,
            "can": "None",
            "modbus": LaunchConfiguration("left_hand_port"),
        }],
    )
    right_hand = Node(
        package="linker_hand_ros2_sdk",
        executable="linker_hand_sdk",
        name="right_linker_hand_sdk",
        output="screen",
        parameters=[{
            "hand_type": "right",
            "hand_joint": LaunchConfiguration("hand_joint"),
            "is_touch": True,
            "can": "None",
            "modbus": LaunchConfiguration("right_hand_port"),
        }],
    )
    player = Node(
        package="rm_piano_player",
        executable="piano_midi_player",
        name="piano_midi_player",
        output="screen",
        parameters=[
            os.path.join(player_share, "config", "piano_midi.yaml"),
            {
                "midi_file": LaunchConfiguration("midi_file"),
                "execute": ParameterValue(LaunchConfiguration("execute"), value_type=bool),
                "feedback_enabled": ParameterValue(
                    LaunchConfiguration("feedback_enabled"), value_type=bool
                ),
                "tempo_scale": ParameterValue(
                    LaunchConfiguration("tempo_scale"), value_type=float
                ),
                "feedback_tolerance_sec": ParameterValue(
                    LaunchConfiguration("feedback_tolerance_sec"), value_type=float
                ),
            },
        ],
    )
    feedback = Node(
        package="rm_piano_player",
        executable="midi_feedback_monitor.py",
        name="midi_feedback_monitor",
        output="screen",
        parameters=[
            os.path.join(player_share, "config", "piano_midi.yaml"),
            {
                "enabled": ParameterValue(
                    LaunchConfiguration("feedback_enabled"), value_type=bool
                ),
                "midi_input": LaunchConfiguration("midi_input"),
                "tolerance_sec": ParameterValue(
                    LaunchConfiguration("feedback_tolerance_sec"), value_type=float
                ),
            },
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument("left_arm_ip", default_value="192.168.1.18"),
        DeclareLaunchArgument("right_arm_ip", default_value="192.168.1.19"),
        DeclareLaunchArgument("left_udp_ip", default_value="192.168.1.10"),
        DeclareLaunchArgument("right_udp_ip", default_value="192.168.1.10"),
        DeclareLaunchArgument("left_udp_port", default_value="8089"),
        DeclareLaunchArgument("right_udp_port", default_value="8090"),
        DeclareLaunchArgument("left_hand_port", default_value="/dev/ttyUSB0"),
        DeclareLaunchArgument("right_hand_port", default_value="/dev/ttyUSB1"),
        DeclareLaunchArgument("hand_joint", default_value="L20-11"),
        DeclareLaunchArgument("midi_file", default_value=""),
        DeclareLaunchArgument("midi_input", default_value=""),
        DeclareLaunchArgument("execute", default_value="false"),
        DeclareLaunchArgument("feedback_enabled", default_value="false"),
        DeclareLaunchArgument("tempo_scale", default_value="4.0"),
        DeclareLaunchArgument("feedback_tolerance_sec", default_value="0.15"),
        DeclareLaunchArgument("use_rviz", default_value="true"),
        bringup,
        left_hand,
        right_hand,
        TimerAction(period=8.0, actions=[feedback, player]),
    ])
