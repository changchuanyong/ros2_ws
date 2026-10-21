import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from rm_mujoco.scene import key_positions, load_layout


def launch_setup(context):
    mujoco_share = get_package_share_directory("rm_mujoco")
    player_share = get_package_share_directory("rm_piano_player")
    layout = load_layout(LaunchConfiguration("scene_config").perform(context))
    mujoco_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(mujoco_share, "launch", "rm_75_dual_l20_mujoco.launch.py")
        ),
        launch_arguments={
            "headless": LaunchConfiguration("headless"),
            "use_rviz": LaunchConfiguration("use_rviz"),
            "scene_config": LaunchConfiguration("scene_config"),
        }.items(),
    )
    player = Node(
        package="rm_piano_player",
        executable="piano_midi_player",
        name="piano_midi_player",
        output="screen",
        parameters=[
            os.path.join(player_share, "config", "piano_midi.yaml"),
            os.path.join(player_share, "config", "piano_midi_sim.yaml"),
            {
                "use_sim_time": True,
                "key_positions": [value for point in key_positions(layout) for value in point],
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

    return [mujoco_launch, TimerAction(period=8.0, actions=[feedback, player])]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("midi_file", default_value=""),
        DeclareLaunchArgument("midi_input", default_value=""),
        DeclareLaunchArgument("execute", default_value="false"),
        DeclareLaunchArgument("feedback_enabled", default_value="false"),
        DeclareLaunchArgument("tempo_scale", default_value="2.0"),
        DeclareLaunchArgument("feedback_tolerance_sec", default_value="0.15"),
        DeclareLaunchArgument("headless", default_value="false"),
        DeclareLaunchArgument("use_rviz", default_value="true"),
        DeclareLaunchArgument("scene_config", default_value=os.path.join(
            get_package_share_directory("rm_mujoco"), "config", "piano_scene.yaml"
        )),
        OpaqueFunction(function=launch_setup),
    ])
