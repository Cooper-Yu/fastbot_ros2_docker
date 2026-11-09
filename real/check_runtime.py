#!/usr/bin/env python3
"""Observe the Task2 sensor and mapping chain without publishing commands."""

import json
import math
import time

import rclpy
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, LaserScan
from tf2_msgs.msg import TFMessage


def main():
    rclpy.init()
    node = rclpy.create_node("cp23_real_runtime_observer")
    counts = dict.fromkeys(["scan", "image", "odom", "map", "tf"], 0)
    samples = {}
    transforms = set()

    def observe_scan(message):
        counts["scan"] += 1
        finite = [value for value in message.ranges if math.isfinite(value)]
        samples["scan"] = {
            "frame": message.header.frame_id,
            "rays": len(message.ranges),
            "finite": len(finite),
            "minimum": min(finite) if finite else None,
        }

    def observe_image(message):
        counts["image"] += 1
        samples["image"] = {
            "width": message.width,
            "height": message.height,
            "bytes": len(message.data),
            "encoding": message.encoding,
        }

    def observe_odom(message):
        counts["odom"] += 1
        samples["odom"] = {
            "frame": message.header.frame_id,
            "child": message.child_frame_id,
            "linear": message.twist.twist.linear.x,
            "angular": message.twist.twist.angular.z,
        }

    def observe_map(message):
        counts["map"] += 1
        samples["map"] = {
            "frame": message.header.frame_id,
            "width": message.info.width,
            "height": message.info.height,
            "known": sum(value >= 0 for value in message.data),
        }

    def observe_tf(message):
        counts["tf"] += 1
        for transform in message.transforms:
            transforms.add((transform.header.frame_id, transform.child_frame_id))

    subscriptions = []
    for topic, message_type, callback in [
        ("/fastbot/scan", LaserScan, observe_scan),
        ("/fastbot_camera/image_raw", Image, observe_image),
        ("/fastbot/odom", Odometry, observe_odom),
        ("/map", OccupancyGrid, observe_map),
        ("/tf", TFMessage, observe_tf),
    ]:
        subscriptions.append(
            node.create_subscription(
                message_type, topic, callback, qos_profile_sensor_data
            )
        )
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
        if min(counts.values()) >= 3 and ("map", "fastbot_odom") in transforms:
            break
    result = {
        "counts": counts,
        "samples": samples,
        "transforms": sorted(transforms),
        "command_publishers": [
            item.node_name
            for item in node.get_publishers_info_by_topic("/fastbot/cmd_vel")
        ],
        "passed": min(counts.values()) >= 3
        and ("map", "fastbot_odom") in transforms
        and samples.get("map", {}).get("known", 0) > 0
        and samples.get("scan", {}).get("finite", 0) > 0
        and samples.get("image", {}).get("bytes", 0) > 0,
        "scope": "stationary hardware data and mapping; no motion command published",
    }
    print(json.dumps(result, indent=2), flush=True)
    node.destroy_node()
    rclpy.shutdown()
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
