"""Launch only the right hand, with a unique readiness channel per invocation."""

import os
import uuid

from ament_index_python.packages import get_package_share_directory
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
import yaml

from rm_piano_player.single_hand_core import load_pose_config, validate_execution
from rm_piano_player.single_hand_node import playback_parameters


def launch_arguments():
    """Keep empty, unverified calibration as the default."""
    piano_share = get_package_share_directory('rm_piano_player')
    driver_share = get_package_share_directory('rm_l20_driver')
    defaults = {
        'execute': 'false', 'mode': 'pose_test', 'pose': 'READY',
        'pose_config': os.path.join(piano_share, 'config', 'right_hand_ode_to_joy.yaml'),
        'hand_port': 'auto', 'press_duration': '0.5', 'release_duration': '0.5',
        'ready_settle': '1.0',
        'hand_identity_config': os.path.join(driver_share, 'config', 'hand_identity.yaml'),
    }
    return [DeclareLaunchArgument(name, default_value=value) for name, value in defaults.items()]


def launch_actions(context):
    """Validate all executable poses before starting a serial driver process."""
    def value(name):
        return LaunchConfiguration(name).perform(context)

    execute_text = value('execute').lower()
    if execute_text not in ('true', 'false'):
        raise ValueError('execute must be true or false')
    execute = execute_text == 'true'
    options = {'mode': value('mode'), 'pose': value('pose')}
    for name in ('press_duration', 'release_duration', 'ready_settle'):
        options[name] = float(value(name))
    playback_parameters(**options)
    pose_config = value('pose_config')
    config = load_pose_config(pose_config)
    parameters = {**options, 'pose_config': pose_config, 'execute': execute}
    driver = None
    if execute:
        validate_execution(config, options['mode'], options['pose'])
        hand_port = value('hand_port')
        if not hand_port:
            raise ValueError('hand_port must be auto or a serial path')
        with open(value('hand_identity_config'), encoding='utf-8') as stream:
            identity = yaml.safe_load(stream)
        uid = identity['l20_dual_rs485_driver']['ros__parameters']['right_hand_uid']
        if not isinstance(uid, str) or not uid or not all(33 <= ord(c) <= 126 for c in uid):
            raise ValueError('right_hand_uid must be nonempty printable ASCII without spaces')
        run_id = uuid.uuid4().hex
        driver_name = 'l20_right_run_' + run_id
        ready_topic = '/single_hand_piano/run_' + run_id + '/ready'
        fault_topic = '/single_hand_piano/run_' + run_id + '/fault'
        written_topic = '/single_hand_piano/run_' + run_id + '/command_written'
        parameters.update(driver_node=driver_name, ready_topic=ready_topic,
                          fault_topic=fault_topic, written_topic=written_topic)
        driver = Node(
            package='rm_l20_driver', executable='l20_rs485_driver', name=driver_name,
            namespace='/', output='screen',
            parameters=[{'hand_type': 'right', 'hand_joint': 'L20-11',
                         'modbus': hand_port, 'expected_uid': uid}],
            remappings=[('~/ready', ready_topic), ('/robopianist/feedback_abort', fault_topic),
                        ('~/command_written', written_topic)])
    player = Node(package='rm_piano_player', executable='l20_right_hand_piano.py',
                  namespace='/', output='screen', parameters=[parameters])

    def exited(label):
        def handle(event, launch_context):
            if launch_context.is_shutdown:
                return []
            return [EmitEvent(event=Shutdown(reason=f'{label} exited: {event.returncode}'))]
        return handle

    actions = [RegisterEventHandler(OnProcessExit(
        target_action=player, on_exit=exited('Single-hand player')))]
    if driver is not None:
        actions.extend([RegisterEventHandler(OnProcessExit(
            target_action=driver, on_exit=exited('Right L20 driver'))), driver])
    actions.append(player)
    return actions
