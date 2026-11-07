#!/usr/bin/env python3
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint


from rm_mujoco.l20_joint_mapping import HAND_JOINT_SUFFIXES, command_positions


class L20DualCommandBridge(Node):
    def __init__(self):
        super().__init__("l20_dual_command_bridge")
        for side in ("left", "right"):
            publisher = self.create_publisher(
                JointTrajectory,
                f"/{side}_l20_hand_controller/joint_trajectory",
                10,
            )
            self.create_subscription(
                JointState,
                f"/cb_{side}_hand_control_cmd",
                lambda message, side=side, publisher=publisher: self.command_callback(
                    side, publisher, message
                ),
                10,
            )

    def command_callback(self, side, publisher, message):
        if len(message.position) < 20:
            self.get_logger().warning(f"{side} L20 command requires 20 position values")
            return

        positions = command_positions(message.position)

        trajectory = JointTrajectory()
        trajectory.joint_names = [f"{side}_{suffix}" for suffix in HAND_JOINT_SUFFIXES]
        point = JointTrajectoryPoint()
        point.positions = positions
        point.time_from_start.sec = 0
        point.time_from_start.nanosec = 50000000
        trajectory.points = [point]
        publisher.publish(trajectory)


def main(args=None):
    rclpy.init(args=args)
    node = L20DualCommandBridge()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
