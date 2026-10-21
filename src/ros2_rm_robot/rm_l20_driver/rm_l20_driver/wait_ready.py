"""Exit successfully only after fresh dual-hand readiness within ten seconds."""

import time

import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool


def wait_until_ready(node, timeout=10.0):
    """Use volatile samples so a retained success from an old process cannot unlock."""
    ready = False

    def receive(message):
        nonlocal ready
        ready = message.data

    subscription = node.create_subscription(
        Bool, '/l20/hands_ready', receive,
        QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE))
    executor = SingleThreadedExecutor(context=node.context)
    executor.add_node(node)
    try:
        deadline = time.monotonic() + timeout
        while rclpy.ok(context=node.context) and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=min(0.1, max(0.0, deadline - time.monotonic())))
            if ready:
                return True
        return False
    finally:
        executor.shutdown()
        node.destroy_subscription(subscription)


def main(args=None):
    rclpy.init(args=args)
    node = Node('l20_wait_ready')
    status = 1
    try:
        if wait_until_ready(node):
            node.get_logger().info('Both configured L20 hands are ready')
            status = 0
        else:
            node.get_logger().error('Both configured hands were not ready within 10 seconds')
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    raise SystemExit(status)
