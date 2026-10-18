#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint


JOINT_NAMES = [
    "thumb_joint0", "thumb_joint1", "thumb_joint2", "thumb_joint3", "thumb_joint4",
    "index_joint0", "index_joint1", "index_joint2", "index_joint3",
    "middle_joint0", "middle_joint1", "middle_joint2", "middle_joint3",
    "ring_joint0", "ring_joint1", "ring_joint2", "ring_joint3",
    "little_joint0", "little_joint1", "little_joint2", "little_joint3",
]
JOINT_MAP = {0: 10, 1: 5, 2: 0, 3: 15, 4: 15, 5: 6, 6: 1, 7: 16, 8: 16,
             9: 7, 10: 2, 11: 17, 12: 17, 13: 8, 14: 3, 15: 18,
             16: 18, 17: 9, 18: 4, 19: 19, 20: 19}
RANGE_MIN = [0, 0, 0, 0, 0, -0.297, -0.26, -0.26, -0.26, -0.26, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
RANGE_MAX = [0.87, 1.4, 1.4, 1.4, 1.4, 0.683, 0.26, 0.26, 0.26, 0.26, 1.78, 0, 0, 0, 0, 1.29, 1.08, 1.08, 1.08, 1.08]
REVERSE = [-1, -1, -1, -1, -1, -1, 0, 0, 0, 0, -1, 0, 0, 0, 0, -1, -1, -1, -1, -1]


class L20RightCommandBridge(Node):
    def __init__(self):
        super().__init__("l20_right_command_bridge")
        self.publisher = self.create_publisher(
            JointTrajectory, "/l20_hand_controller/joint_trajectory", 10
        )
        self.subscription = self.create_subscription(
            JointState, "/cb_right_hand_control_cmd", self.command_callback, 10
        )

    def command_callback(self, message):
        if len(message.position) < 20:
            self.get_logger().warning("L20 command requires 20 position values")
            return

        arc = [0.0] * 20
        for index in range(20):
            if 11 <= index <= 14:
                continue
            value = max(0.0, min(255.0, float(message.position[index])))
            if REVERSE[index] == -1:
                arc[index] = (255.0 - value) / 255.0 * (RANGE_MAX[index] - RANGE_MIN[index]) + RANGE_MIN[index]
            else:
                arc[index] = value / 255.0 * (RANGE_MAX[index] - RANGE_MIN[index]) + RANGE_MIN[index]

        positions = [0.0] * len(JOINT_NAMES)
        for target_index, source_index in JOINT_MAP.items():
            positions[target_index] = arc[source_index]

        trajectory = JointTrajectory()
        trajectory.joint_names = JOINT_NAMES
        point = JointTrajectoryPoint()
        point.positions = positions
        point.time_from_start.sec = 0
        point.time_from_start.nanosec = 50000000
        trajectory.points = [point]
        self.publisher.publish(trajectory)


def main(args=None):
    rclpy.init(args=args)
    node = L20RightCommandBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
