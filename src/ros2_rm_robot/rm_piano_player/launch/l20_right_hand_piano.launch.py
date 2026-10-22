"""Preview or play a calibrated right L20-11 without arm or MIDI nodes."""

from launch import LaunchDescription
from launch.actions import OpaqueFunction

from rm_piano_player.single_hand_launch import launch_actions, launch_arguments


def generate_launch_description():
    return LaunchDescription(launch_arguments() + [OpaqueFunction(function=launch_actions)])
