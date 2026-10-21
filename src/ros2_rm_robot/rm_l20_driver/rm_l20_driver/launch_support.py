"""Shared dual-hand launch configuration and fail-closed startup callbacks."""

import os
import uuid

from ament_index_python.packages import get_package_share_directory
from launch.actions import DeclareLaunchArgument, EmitEvent
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def hand_arguments():
    """Use one installed identity file for both hardware launch entry points."""
    config = os.path.join(
        get_package_share_directory('rm_l20_driver'), 'config', 'hand_identity.yaml')
    return [
        DeclareLaunchArgument('hand_identity_config', default_value=config),
        DeclareLaunchArgument('left_hand_port', default_value='auto'),
        DeclareLaunchArgument('right_hand_port', default_value='auto'),
        DeclareLaunchArgument('hand_joint', default_value='L20-11'),
        DeclareLaunchArgument('baudrate', default_value='115200'),
        DeclareLaunchArgument('slave_id', default_value='1'),
        DeclareLaunchArgument('poll_rate', default_value='20.0'),
    ]


def dual_hand_node(startup_topic=None):
    return Node(
        package='rm_l20_driver', executable='l20_dual_rs485_driver', output='screen',
        remappings=[('~/hands_ready', startup_topic)] if startup_topic else [],
        parameters=[LaunchConfiguration('hand_identity_config'), {
            'left_hand_port': LaunchConfiguration('left_hand_port'),
            'right_hand_port': LaunchConfiguration('right_hand_port'),
            'hand_joint': LaunchConfiguration('hand_joint'),
            'baudrate': ParameterValue(LaunchConfiguration('baudrate'), value_type=int),
            'slave_id': ParameterValue(LaunchConfiguration('slave_id'), value_type=int),
            'poll_rate': ParameterValue(LaunchConfiguration('poll_rate'), value_type=float),
        }])


def gated_hand_nodes():
    """Another running driver's heartbeat must not release this launch's gate."""
    topic = '/l20/startup/run_' + uuid.uuid4().hex
    return dual_hand_node(topic), Node(
        package='rm_l20_driver', executable='l20_wait_ready', output='screen',
        remappings=[('/l20/hands_ready', topic)])


def hand_exit(event, context):
    if context.is_shutdown:
        return []
    return [EmitEvent(event=Shutdown(reason=f'L20 driver exited: {event.returncode}'))]


def readiness_exit(actions):
    """Only successful readiness may release the deferred hardware actions."""
    def handle(event, context):
        if context.is_shutdown:
            return []
        if event.returncode == 0:
            return list(actions)
        return [EmitEvent(event=Shutdown(reason='L20 readiness failed or timed out'))]
    return handle
