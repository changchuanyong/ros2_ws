#!/usr/bin/env python3
"""Verify robot piano events against note messages from a MIDI keyboard."""

import json
import time
from collections import defaultdict, deque

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile
from std_msgs.msg import Bool, String


class MidiFeedbackMonitor(Node):
    def __init__(self):
        super().__init__("midi_feedback_monitor")
        self.declare_parameter("enabled", False)
        self.declare_parameter("midi_input", "")
        self.declare_parameter("tolerance_sec", 0.15)
        self.enabled = bool(self.get_parameter("enabled").value)
        self.midi_input = str(self.get_parameter("midi_input").value)
        self.tolerance_sec = float(self.get_parameter("tolerance_sec").value)
        self.expected = defaultdict(deque)
        self.failed = False
        self.input_port = None
        self.feedback_abort_pub = self.create_publisher(Bool, "/robopianist/feedback_abort", 10)
        self.status_pub = self.create_publisher(String, "/robopianist/feedback_status", 10)
        expected_qos = QoSProfile(depth=10)
        expected_qos.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL
        self.create_subscription(
            String,
            "/robopianist/expected_event",
            self.expected_callback,
            expected_qos,
        )
        self.create_timer(0.01, self.poll_midi)

        if not self.enabled:
            self.publish_status("disabled")
            return
        if not self.midi_input:
            raise RuntimeError("midi_input must be set when feedback is enabled")
        try:
            import mido
        except ImportError as exc:
            raise RuntimeError("MIDI feedback requires mido and python-rtmidi") from exc
        self.mido = mido
        self.input_port = mido.open_input(self.midi_input)
        self.get_logger().info("Listening for MIDI feedback on %s", self.midi_input)

    def expected_callback(self, message: String):
        if not self.enabled:
            return
        try:
            event = json.loads(message.data)
            note = int(event["note"])
            event_type = str(event["type"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.get_logger().warning("Invalid expected MIDI event: %s", exc)
            return
        expected_at = time.monotonic()
        self.expected[(event_type, note)].append(
            (expected_at, expected_at + self.tolerance_sec)
        )
        self.publish_feedback(
            event_type,
            note,
            None,
            None,
            "expected",
        )

    def poll_midi(self):
        if not self.enabled or self.input_port is None:
            return
        now = time.monotonic()
        expired = [
            key
            for key, queue in self.expected.items()
            if queue and queue[0][1] < now
        ]
        if expired:
            event_type, note = expired[0]
            self.publish_feedback(event_type, note, None, None, "missing")
            self.fail("missing MIDI feedback: %s" % (expired[0],))
            self.expected.clear()
            return

        for message in self.input_port.iter_pending():
            if message.type not in ("note_on", "note_off"):
                continue
            event_type = "on" if message.type == "note_on" and message.velocity > 0 else "off"
            key = (event_type, int(message.note))
            queue = self.expected.get(key)
            if not queue:
                self.publish_feedback(event_type, None, int(message.note), None, "unexpected")
                self.fail("unexpected %s note %d" % (event_type, message.note))
                continue
            expected_at, _ = queue.popleft()
            if not queue:
                self.expected.pop(key, None)
            actual_at = time.monotonic()
            error_sec = actual_at - expected_at
            if abs(error_sec) > self.tolerance_sec:
                self.publish_feedback(
                    event_type,
                    int(message.note),
                    int(message.note),
                    error_sec,
                    "late",
                )
                self.fail(
                    "late MIDI feedback: %s note %d error %.3fs"
                    % (event_type, message.note, error_sec)
                )
                continue
            self.publish_feedback(
                event_type,
                int(message.note),
                int(message.note),
                error_sec,
                "matched",
            )
            self.publish_status("matched %s note %d" % (event_type, message.note))

    def fail(self, reason: str):
        if self.failed:
            return
        self.failed = True
        self.get_logger().error(reason)
        self.publish_status(reason)
        message = Bool()
        message.data = True
        self.feedback_abort_pub.publish(message)

    def publish_feedback(self, event_type, expected_note, actual_note, error_sec, state):
        payload = {
            "state": state,
            "type": event_type,
            "expected_note": expected_note,
            "actual_note": actual_note,
            "time_error_sec": error_sec,
        }
        message = String()
        message.data = json.dumps(payload, separators=(",", ":"))
        self.status_pub.publish(message)

    def publish_status(self, text: str):
        message = String()
        message.data = text
        self.status_pub.publish(message)

    def close(self):
        if self.input_port is not None:
            self.input_port.close()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = MidiFeedbackMonitor()
        rclpy.spin(node)
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
