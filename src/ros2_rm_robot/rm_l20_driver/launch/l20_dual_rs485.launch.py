from launch import LaunchDescription
from launch.actions import RegisterEventHandler
from launch.event_handlers import OnProcessExit

from rm_l20_driver.launch_support import dual_hand_node, hand_arguments, hand_exit


def generate_launch_description():
    hands = dual_hand_node()
    return LaunchDescription(hand_arguments() + [
        RegisterEventHandler(OnProcessExit(target_action=hands, on_exit=hand_exit)),
        hands,
    ])
