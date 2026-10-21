"""Own both verified connections and disable both hands on any hand failure."""

import math

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool

from rm_l20_driver.discovery import close_bindings, discover_hands
from rm_l20_driver.node import L20RS485Driver


def ready_qos():
    """Retain readiness for a late subscriber, while publishing a live heartbeat."""
    return QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)


class DualHandDriver(Node):
    """One executor owns discovery, both hand nodes, and their shared command gate."""

    def __init__(self, **kwargs):
        super().__init__('l20_dual_rs485_driver', **kwargs)
        self.ready = False
        self.faulted = False
        self.hands = []
        self.bindings = {}
        for name, default in (
                ('left_hand_uid', ''), ('right_hand_uid', ''),
                ('left_hand_port', 'auto'), ('right_hand_port', 'auto'),
                ('hand_joint', 'L20-11'), ('baudrate', 115200),
                ('slave_id', 1), ('poll_rate', 20.0)):
            self.declare_parameter(name, default)
        self.ready_publisher = self.create_publisher(Bool, '/l20/hands_ready', ready_qos())
        # Launch remaps this private channel per run, isolating its startup gate.
        self.startup_publisher = self.create_publisher(Bool, '~/hands_ready', ready_qos())
        self.ready_timer = self.create_timer(1.0, self.publish_ready)
        self.publish_ready()

    def publish_ready(self):
        message = Bool(data=self.ready and not self.faulted)
        self.ready_publisher.publish(message)
        self.startup_publisher.publish(message)

    def initialize(self):
        """Keep every command gate closed until both first state reads succeed."""
        values = {name: self.get_parameter(name).value for name in (
            'hand_joint', 'baudrate', 'slave_id', 'poll_rate')}
        if values['hand_joint'] not in ('L20-10', 'L20-11'):
            raise ValueError('hand_joint must be L20-10 or L20-11')
        if values['baudrate'] <= 0 or not 1 <= values['slave_id'] <= 247:
            raise ValueError('invalid baudrate or slave_id')
        if not math.isfinite(values['poll_rate']) or not 0 < values['poll_rate'] <= 100:
            raise ValueError('poll_rate must be finite and within (0, 100] Hz')
        expected = {side: self.get_parameter(f'{side}_hand_uid').value
                    for side in ('left', 'right')}
        ports = {side: self.get_parameter(f'{side}_hand_port').value
                 for side in ('left', 'right')}
        self.bindings = discover_hands(
            expected, ports, baudrate=values['baudrate'], slave_id=values['slave_id'],
            report=self.get_logger().info)
        try:
            for side in ('left', 'right'):
                binding = self.bindings.pop(side)
                params = dict(values, hand_type=side, modbus=binding.port, expected_uid=binding.uid)
                try:
                    node = L20RS485Driver(
                        connected_hand=binding.hand, verified_uid=binding.uid,
                        command_gate=lambda: self.ready and not self.faulted,
                        fault_callback=self.fail, node_name=f'{side}_l20_driver',
                        context=self.context, use_global_arguments=False,
                        parameter_overrides=[Parameter(key, value=value) for key, value in params.items()])
                except BaseException:
                    binding.hand.close()
                    raise
                self.hands.append(node)
                if node._faulted or self.faulted:
                    raise RuntimeError(f'{side} initial state read failed')
                self.get_logger().info(f'{side}: UID={binding.uid}, port={binding.port}')
            self.ready = True
            for node in self.hands:
                node.enable_commands()
            self.publish_ready()
        except BaseException:
            self.fail('dual-hand initialization failed')
            raise

    def fail(self, reason):
        """Latch the shared gate before closing either connection or publishing abort."""
        if self.faulted:
            return
        self.faulted = True
        self.ready = False
        self.publish_ready()
        for node in self.hands:
            node._enter_fault(f'dual-hand fault: {reason}')
        close_bindings(self.bindings, self.get_logger().error)

    def destroy_node(self):
        self.ready = False
        self.ready_timer.cancel()
        if rclpy.ok(context=self.context):
            self.publish_ready()
        for node in self.hands:
            node.destroy_node()
        self.hands.clear()
        close_bindings(self.bindings, self.get_logger().error)
        self.bindings.clear()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    manager = None
    executor = SingleThreadedExecutor()
    try:
        manager = DualHandDriver()
        manager.initialize()
        executor.add_node(manager)
        for node in manager.hands:
            executor.add_node(node)
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except Exception as error:
        if manager is not None:
            manager.get_logger().error(f'L20 startup failed: {error}')
        raise SystemExit(1) from error
    finally:
        executor.shutdown()
        if manager is not None:
            manager.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
