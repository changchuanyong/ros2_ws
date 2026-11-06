"""Measure fixed-wrist right-hand piano speed using actual MIDI feedback."""

from launch import LaunchDescription
from launch.actions import OpaqueFunction

from rm_piano_player.speed_test_launch import launch_actions, launch_arguments


def generate_launch_description():
    return LaunchDescription(launch_arguments() + [OpaqueFunction(function=launch_actions)])
