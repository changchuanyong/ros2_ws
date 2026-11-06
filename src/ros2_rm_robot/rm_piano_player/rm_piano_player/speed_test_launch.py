"""Launch a calibrated right-hand speed test with private transport channels."""

import math
import os
import uuid

from ament_index_python.packages import get_package_share_directory
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
import yaml

from rm_piano_player.midi_capture import list_inputs
from rm_piano_player.single_hand_core import load_pose_config, validate_execution
from rm_piano_player.speed_test_core import PATTERNS, parse_rates


def launch_arguments():
    """Require an explicit motion request and confirmation of physical calibration."""
    piano = get_package_share_directory('rm_piano_player')
    driver = get_package_share_directory('rm_l20_driver')
    defaults = {
        'execute': 'false', 'calibration_confirmed': 'false', 'pattern': 'repeat',
        'rates': '2,4,6,8,10,12,16', 'notes_per_trial': '20', 'repeats': '3',
        'ready_settle': '1.0', 'trial_rest': '1.0', 'midi_input': '', 'hand_port': 'auto',
        'record_dir': os.path.expanduser('~/l20_speed_tests'),
        'pose_config': os.path.join(piano, 'config', 'right_hand_ode_to_joy.yaml'),
        'hand_identity_config': os.path.join(driver, 'config', 'hand_identity.yaml'),
        'telemetry_rate': '10.0', 'matrix_rate': '5.0',
    }
    return [DeclareLaunchArgument(key, default_value=value) for key, value in defaults.items()]


def launch_actions(context):
    """Reject invalid calibration or unavailable MIDI before creating any driver."""
    def value(name, default=None):
        return LaunchConfiguration(name, default=default).perform(context)

    def boolean(name):
        text = value(name, 'false').lower()
        if text not in ('true', 'false'):
            raise ValueError(f'{name} must be true or false')
        return text == 'true'

    execute, confirmed = boolean('execute'), boolean('calibration_confirmed')
    pattern, rates = value('pattern', 'repeat'), value('rates', '2,4,6,8,10,12,16')
    if pattern not in PATTERNS:
        raise ValueError('pattern must be repeat, alternate or scale')
    parse_rates(rates)
    parameters = {
        'execute': execute, 'calibration_confirmed': confirmed, 'pattern': pattern,
        'rates': rates, 'pose_config': value('pose_config'), 'mode': 'melody', 'record': True,
        'record_dir': value('record_dir', os.path.expanduser('~/l20_speed_tests')),
        'midi_input': value('midi_input', ''),
    }
    if not parameters['record_dir'].strip():
        raise ValueError('record_dir must not be empty')
    for name, default, maximum in (('notes_per_trial', '20', 1000), ('repeats', '3', 10)):
        parameters[name] = int(value(name, default))
        if not 1 <= parameters[name] <= maximum:
            raise ValueError(f'{name} must be within 1..{maximum}')
    for name, default, maximum in (
            ('ready_settle', '1.0', None), ('trial_rest', '1.0', None),
            ('telemetry_rate', '10.0', 20), ('matrix_rate', '5.0', 10)):
        number = float(value(name, default))
        if not math.isfinite(number) or number <= 0 or (maximum and number > maximum):
            raise ValueError(f'invalid {name}')
        parameters[name] = number
    config = load_pose_config(parameters['pose_config'])
    driver = None
    if execute:
        if not confirmed:
            raise ValueError('complete physical key calibration, then set '
                             'calibration_confirmed:=true')
        validate_execution(config, 'melody')
        if not parameters['midi_input']:
            raise ValueError('midi_input must name the digital piano input exactly')
        if list_inputs().count(parameters['midi_input']) != 1:
            raise ValueError('requested MIDI input must match exactly one available port')
        hand_port = value('hand_port', 'auto')
        if not hand_port:
            raise ValueError('hand_port must be auto or a serial device')
        with open(value('hand_identity_config'), encoding='utf-8') as stream:
            uid = yaml.safe_load(stream)[
                'l20_dual_rs485_driver']['ros__parameters']['right_hand_uid']
        if not isinstance(uid, str) or not uid or not all(33 <= ord(c) <= 126 for c in uid):
            raise ValueError('right_hand_uid must be nonempty printable ASCII without spaces')
        run_id = uuid.uuid4().hex
        prefix = '/single_hand_piano/speed_run_' + run_id
        parameters.update(session_id=run_id, hand_uid=uid, driver_node='l20_speed_' + run_id,
                          ready_topic=prefix + '/ready', fault_topic=prefix + '/fault',
                          written_topic=prefix + '/written', telemetry_topic=prefix + '/telemetry')
        driver = Node(
            package='rm_l20_driver', executable='l20_rs485_driver', namespace='/',
            name=parameters['driver_node'], output='screen',
            parameters=[{'hand_type': 'right', 'hand_joint': 'L20-11', 'modbus': hand_port,
                         'expected_uid': uid, 'telemetry_enabled': True, 'session_id': run_id,
                         'telemetry_rate': parameters['telemetry_rate'],
                         'matrix_rate': parameters['matrix_rate']}],
            remappings=[('~/ready', parameters['ready_topic']),
                        ('/robopianist/feedback_abort', parameters['fault_topic']),
                        ('~/command_written', parameters['written_topic']),
                        ('~/telemetry', parameters['telemetry_topic'])])
    player = Node(
        package='rm_piano_player', executable='l20_right_hand_speed_test.py',
        namespace='/', output='screen', parameters=[parameters],
        remappings=[('/single_hand_piano/status', '/single_hand_piano/speed_status'),
                    ('/single_hand_piano/stop', '/single_hand_piano/speed_stop')])

    def exited(label):
        def handle(event, launch_context):
            if launch_context.is_shutdown:
                return []
            return [EmitEvent(event=Shutdown(reason=f'{label} exited: {event.returncode}'))]
        return handle

    actions = [RegisterEventHandler(OnProcessExit(
        target_action=player, on_exit=exited('Speed test')))]
    if driver is not None:
        actions.extend([RegisterEventHandler(OnProcessExit(
            target_action=driver, on_exit=exited('Right L20 driver'))), driver])
    return actions + [player]
