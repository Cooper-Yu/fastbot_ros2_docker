#!/usr/bin/env python3
"""Coach support: bounded manual input relay for the CP23 isolated simulation."""

import json
import math
import os
import signal
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import String

MAX_LINEAR = 0.05
MAX_ANGULAR = 0.30
COMMAND_MAX_AGE = 0.30
ODOM_MAX_AGE = 0.50


class ManualBridge(Node):
    """Relay one manual source; stale input or feedback always produces zero."""

    def __init__(self):
        super().__init__('cp23_manual_bridge')
        self.output = self.create_publisher(Twist, '/fastbot/cmd_vel', 1)
        self.status_output = self.create_publisher(String, '/web/manual_status', 1)
        self.input_subscription = self.create_subscription(
            Twist, '/web/manual_cmd', self.on_command, 1
        )
        self.odom_subscription = self.create_subscription(
            Odometry, '/fastbot/odom', self.on_odom, qos_profile_sensor_data
        )
        self.target = (0.0, 0.0)
        self.last_command = None
        self.last_odom = None
        self.odom_stamp = None
        self.tick_number = 0
        self.wall_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.timer = self.create_timer(0.05, self.tick, clock=self.wall_clock)

    def on_command(self, command):
        values = [
            command.linear.x,
            command.linear.y,
            command.linear.z,
            command.angular.x,
            command.angular.y,
            command.angular.z,
        ]
        if not all(math.isfinite(v) for v in values) or any(
            abs(v) > 1e-9 for v in [values[1], values[2], values[3], values[4]]
        ):
            self.stop_output()
            return
        if not self.readiness(time.monotonic())[0]:
            self.stop_output()
            return
        self.target = (
            max(-MAX_LINEAR, min(MAX_LINEAR, command.linear.x)),
            max(-MAX_ANGULAR, min(MAX_ANGULAR, command.angular.z)),
        )
        self.last_command = time.monotonic()

    def on_odom(self, message):
        stamp = message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec
        values = [message.twist.twist.linear.x, message.twist.twist.angular.z]
        if stamp > (self.odom_stamp or 0) and all(math.isfinite(v) for v in values):
            self.odom_stamp = stamp
            self.last_odom = time.monotonic()

    def readiness(self, now):
        if self.last_odom is None or now - self.last_odom > ODOM_MAX_AGE:
            return False, '等待新鲜里程计反馈'
        publishers = self.get_publishers_info_by_topic('/fastbot/cmd_vel')
        if len(publishers) != 1 or publishers[0].node_name != self.get_name():
            return False, '速度输出存在其他发布者或发现尚未完成'
        return True, '仿真手动控制就绪'

    def tick(self):
        now = time.monotonic()
        ready, reason = self.readiness(now)
        input_fresh = self.last_command is not None and now - self.last_command <= COMMAND_MAX_AGE
        output = Twist()
        if ready and input_fresh:
            output.linear.x, output.angular.z = self.target
        self.output.publish(output)
        self.tick_number += 1
        if self.tick_number % 2 == 0:
            status = {
                'ready': ready,
                'reason': reason,
                'input_fresh': input_fresh,
                'linear': output.linear.x,
                'angular': output.angular.z,
                'max_linear': MAX_LINEAR,
                'max_angular': MAX_ANGULAR,
                'command_max_age': COMMAND_MAX_AGE,
                'odom_max_age': ODOM_MAX_AGE,
            }
            self.status_output.publish(String(data=json.dumps(status, ensure_ascii=False)))

    def stop_output(self):
        self.target = (0.0, 0.0)
        self.last_command = None
        self.output.publish(Twist())


def interrupt(_signum, _frame):
    raise KeyboardInterrupt


def main():
    if os.environ.get('CP23_ENABLE_SIM_MANUAL') != '1':
        raise SystemExit('Simulation manual relay requires CP23_ENABLE_SIM_MANUAL=1')
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    node = ManualBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        for _ in range(3):
            node.stop_output()
            rclpy.spin_once(node, timeout_sec=0.02)
            time.sleep(0.03)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
