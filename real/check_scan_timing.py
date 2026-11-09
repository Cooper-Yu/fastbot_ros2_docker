#!/usr/bin/env python3
"""Capture the first published scans and reject invalid sweep timestamps."""

import json
import math
import time
from itertools import pairwise

import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


def main():
    rclpy.init()
    node = rclpy.create_node("cp23_scan_startup_timing")
    samples = []

    def observe(message):
        stamp = message.header.stamp.sec + message.header.stamp.nanosec / 1e9
        received = node.get_clock().now().nanoseconds / 1e9
        last_ray = stamp + max(0, len(message.ranges) - 1) * message.time_increment
        samples.append(
            {
                "stamp": stamp,
                "scan_time": message.scan_time,
                "time_increment": message.time_increment,
                "last_ray_minus_receive": last_ray - received,
            }
        )

    subscription = node.create_subscription(
        LaserScan, "/fastbot/scan", observe, qos_profile_sensor_data
    )
    print("CP23_SCAN_TIMING_READY", flush=True)
    deadline = time.monotonic() + 60
    while len(samples) < 12 and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    durations_valid = all(
        math.isfinite(sample["scan_time"]) and 0 < sample["scan_time"] < 1
        for sample in samples
    )
    stamps_valid = all(
        sample["time_increment"] > 0 and -2 < sample["last_ray_minus_receive"] < 0.05
        for sample in samples
    )
    chronological = all(
        left["stamp"] < right["stamp"] for left, right in pairwise(samples)
    )
    result = {
        "first_scans": samples[:12],
        "passed": len(samples) >= 12
        and durations_valid
        and stamps_valid
        and chronological,
    }
    print("CP23_SCAN_TIMING_RESULT=" + json.dumps(result), flush=True)
    node.destroy_subscription(subscription)
    node.destroy_node()
    rclpy.shutdown()
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
