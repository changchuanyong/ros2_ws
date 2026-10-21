"""ROS 2 interface for the vendored L20-10/L20-11 RS485 protocol."""

import math

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool

from rm_l20_driver.discovery import open_hand, read_verified_uid, validate_uid
from rm_l20_driver.protocol import KEYS


def validate_positions(values):
    """Validate the SDK's 20 raw position values without clipping or scaling."""
    if len(values) != 20:
        raise ValueError('expected exactly 20 values in SDK order')
    result = [float(value) for value in values]
    if any(not math.isfinite(value) or not 0 <= value <= 255 for value in result):
        raise ValueError('all 20 values must be finite and within 0..255')
    return result


def validate_feedback(values):
    """Preserve 20 raw uint16 feedback registers, including reserved slots."""
    if len(values) != 20:
        raise ValueError('expected exactly 20 feedback values in SDK order')
    result = [float(value) for value in values]
    if any(not math.isfinite(value) or not 0 <= value <= 65535 for value in result):
        raise ValueError('feedback values must be finite and within 0..65535')
    return result


class L20RS485Driver(Node):
    """Serialize hand commands and fresh feedback on a single ROS executor."""

    def __init__(self, *, connected_hand=None, verified_uid=None,
                 command_gate=lambda: True, fault_callback=None,
                 node_name='l20_rs485_driver', **kwargs):
        """Open the serial connection without sending an initial hand pose."""
        super().__init__(node_name, **kwargs)
        self._hand = None
        self._faulted = False
        self._commands_enabled = False
        self._command_gate = command_gate
        self._fault_callback = fault_callback
        self._timer = None
        self._abort_timer = None
        try:
            self.declare_parameter('hand_type', 'left')
            self.declare_parameter('hand_joint', 'L20-11')
            self.declare_parameter('modbus', '/dev/ttyUSB0')
            self.declare_parameter('expected_uid', '')
            self.declare_parameter('baudrate', 115200)
            self.declare_parameter('slave_id', 1)
            self.declare_parameter('poll_rate', 20.0)

            self.hand_type = self.get_parameter('hand_type').value
            hand_joint = self.get_parameter('hand_joint').value
            port = self.get_parameter('modbus').value
            expected_uid = self.get_parameter('expected_uid').value
            validate_uid(expected_uid)
            baudrate = self.get_parameter('baudrate').value
            slave_id = self.get_parameter('slave_id').value
            poll_rate = self.get_parameter('poll_rate').value
            if self.hand_type not in ('left', 'right'):
                raise ValueError('hand_type must be left or right')
            if hand_joint not in ('L20-11', 'L20-10'):
                raise ValueError('hand_joint must be L20-11 or L20-10 for RS485')
            if not port:
                raise ValueError('modbus must identify a serial device')
            if baudrate <= 0:
                raise ValueError('baudrate must be positive')
            if not 1 <= slave_id <= 247:
                raise ValueError('slave_id must be within 1..247')
            if not math.isfinite(poll_rate) or not 0 < poll_rate <= 100:
                raise ValueError('poll_rate must be finite and within (0, 100] Hz')
        except Exception:
            super().destroy_node()
            raise

        self.state_publisher = self.create_publisher(
            JointState, f'/cb_{self.hand_type}_hand_state', 10)
        self.command_subscription = None
        self.abort_publisher = self.create_publisher(
            Bool, '/robopianist/feedback_abort',
            QoSProfile(
                depth=1, reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self._timer = self.create_timer(1.0 / poll_rate, self.poll_state)
        try:
            self._hand = connected_hand if connected_hand is not None else open_hand(
                port, baudrate, slave_id)
            uid = verified_uid if connected_hand is not None else read_verified_uid(self._hand)
            if uid != expected_uid:
                raise ValueError(f'expected UID {expected_uid}, got {uid}')
            self.poll_state()
            if not self._faulted and connected_hand is None:
                self.enable_commands()
        except Exception as error:
            self._enter_fault(f'cannot connect to {port}: {error}')
        else:
            if not self._faulted:
                self.get_logger().info(
                    f'{self.hand_type} {hand_joint} RS485 connected: '
                    f'{port}, UID={expected_uid}, baudrate={baudrate}, slave_id={slave_id}; '
                    'waiting for explicit position commands')

    def enable_commands(self):
        """Subscribe only after readiness, so startup commands cannot queue for later."""
        if self._faulted or self._hand is None or not self._command_gate():
            return
        if self.command_subscription is None:
            self.command_subscription = self.create_subscription(
                JointState, f'/cb_{self.hand_type}_hand_control_cmd',
                self.command_callback, 10)
        self._commands_enabled = True

    def command_callback(self, message):
        """Forward only valid position commands; never recover a fault silently."""
        if (self._faulted or self._hand is None or not self._commands_enabled or
                not self._command_gate()):
            return
        try:
            positions = validate_positions(message.position)
        except (TypeError, ValueError, OverflowError) as error:
            self.get_logger().warning(f'Rejected L20 position command: {error}')
            return
        try:
            self._hand.set_joint_positions(positions)
        except Exception as error:
            self._enter_fault(f'position write failed: {error}')

    def poll_state(self):
        """Publish a complete fresh sample, never the previous successful read."""
        if self._faulted or self._hand is None:
            return
        try:
            positions = validate_feedback(self._hand.get_state())
            speeds = validate_feedback(self._hand.get_speed())
        except Exception as error:
            self._enter_fault(f'state read failed: {error}')
            return
        message = JointState()
        message.header.stamp = self.get_clock().now().to_msg()
        message.name = list(KEYS)
        message.position = positions
        message.velocity = speeds
        # The original SDK's generic ROS node publishes zero effort.
        message.effort = [0.0] * 20
        self.state_publisher.publish(message)

    def _close_hand(self):
        hand, self._hand = self._hand, None
        if hand is not None:
            try:
                hand.close()
            except Exception as error:
                self.get_logger().error(f'RS485 close failed: {error}')

    def _enter_fault(self, reason):
        if self._faulted:
            return
        self._faulted = True
        self._commands_enabled = False
        if self._fault_callback is not None:
            self._fault_callback(reason)
        if self._timer is not None:
            self._timer.cancel()
        self.get_logger().error(
            f'{self.hand_type} L20 fault; commands disabled until restart: {reason}')
        self._close_hand()
        self._publish_abort()
        # The existing player has a volatile subscription and can join later.
        self._abort_timer = self.create_timer(0.5, self._publish_abort)

    def _publish_abort(self):
        self.abort_publisher.publish(Bool(data=True))

    def destroy_node(self):
        """Release serial resources without sending an opening or closing pose."""
        self._commands_enabled = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._abort_timer is not None:
            self._abort_timer.cancel()
            self._abort_timer = None
        self._close_hand()
        return super().destroy_node()


def main(args=None):
    """Run command and polling callbacks serially, including during shutdown."""
    rclpy.init(args=args)
    node = None
    executor = SingleThreadedExecutor()
    try:
        node = L20RS485Driver()
        executor.add_node(node)
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
