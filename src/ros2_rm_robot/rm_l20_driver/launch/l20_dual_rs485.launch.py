import uuid

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, RegisterEventHandler
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from rm_l20_driver.gui_launch import check_gui_environment, gui_exit
from rm_l20_driver.launch_support import dual_hand_node, hand_arguments, hand_exit


def generate_launch_description():
    startup_topic = '/l20/startup/run_' + uuid.uuid4().hex
    hands = dual_hand_node(startup_topic)
    gui = Node(
        package='rm_l20_driver', executable='l20_hand_gui', output='screen',
        parameters=[{'ready_topic': startup_topic}],
        condition=IfCondition(LaunchConfiguration('use_gui')))
    return LaunchDescription(hand_arguments() + [
        DeclareLaunchArgument('use_gui', default_value='false'),
        OpaqueFunction(function=check_gui_environment,
                       condition=IfCondition(LaunchConfiguration('use_gui'))),
        RegisterEventHandler(OnProcessExit(target_action=hands, on_exit=hand_exit)),
        RegisterEventHandler(OnProcessExit(target_action=gui, on_exit=gui_exit)),
        hands,
        gui,
    ])
