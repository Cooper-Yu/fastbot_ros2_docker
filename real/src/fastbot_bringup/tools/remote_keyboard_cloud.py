"""One official keyboard i/k stimulus, only after the host advertises readiness."""

import json
import os
import pty
import re
import subprocess
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import Twist
from std_msgs.msg import String
import teleop_twist_keyboard

topic = '__CP21_TOPIC__'
assert topic.startswith('/cp21_remote_'), 'Set a fresh, reviewed isolated test topic first'
master, slave = pty.openpty()
rclpy.init()
node = rclpy.create_node('cp21_remote_keyboard_observer')
received = []
ready = []
node.create_subscription(
    Twist, topic, lambda msg: received.append((msg.linear.x, msg.angular.z)), 10
)
node.create_subscription(String, topic + '/ready', lambda msg: ready.append(msg.data), 10)
keyboard = None
result = {'result': 'FAIL', 'nonzero_keys': 0, 'stop_key_sent': False}
try:
    with open('/tmp/cp21-remote-keyboard.log', 'w') as log:
        keyboard = subprocess.Popen(
            [
                'ros2',
                'run',
                'teleop_twist_keyboard',
                'teleop_twist_keyboard',
                '--ros-args',
                '-p',
                'speed:=0.03',
                '-p',
                'turn:=0.3',
                '-r',
                'cmd_vel:=' + topic,
            ],
            stdin=slave,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'},
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and not ready:
            rclpy.spin_once(node, timeout_sec=0.05)
        assert ready and ready[-1] == 'READY', 'Host did not advertise stable readiness'
        assert node.count_publishers(topic) == 1, 'Competing command publishers'
        assert node.count_subscribers(topic) == 3, 'Unexpected command subscribers'
        # This cloud version hardcodes speed=0.5; use its own zero-motion speed keys.
        assert teleop_twist_keyboard.speedBindings['z'] == (0.9, 0.9)
        for index in range(27):
            os.write(master, b'z')
            deadline = time.monotonic() + 1.5
            observed_speed = None
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.02)
                values = re.findall(
                    r'speed\s+([0-9.eE+-]+)', Path('/tmp/cp21-remote-keyboard.log').read_text()
                )
                if values:
                    observed_speed = float(values[-1])
                    if abs(observed_speed - 0.5 * 0.9 ** (index + 1)) < 1e-8:
                        break
            assert (
                observed_speed is not None and abs(observed_speed - 0.5 * 0.9 ** (index + 1)) < 1e-8
            )
            assert not any(x != 0 or z != 0 for x, z in received)
        result['speed_reduction_keys'] = 27
        result['observed_forward_speed'] = observed_speed
        result['expected_forward_speed'] = 0.5 * 0.9**27
        print('CP21_REMOTE_FORWARD_STARTING', flush=True)
        os.write(master, b'i')
        result['nonzero_keys'] = 1
        start = time.monotonic()
        try:
            while time.monotonic() - start < 0.3:
                rclpy.spin_once(node, timeout_sec=0.02)
        finally:
            os.write(master, b'k')
            result['stop_key_sent'] = True
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        forward = [(x, z) for x, z in received if x > 0]
        assert len(forward) == 1 and 0.028 < forward[0][0] < 0.031 and forward[0][1] == 0
        assert received[-1] == (0.0, 0.0)
        result.update(result='PASS', command_messages=received)
finally:
    if keyboard is not None:
        os.write(master, b'\x03')
        try:
            keyboard.wait(timeout=3)
        except subprocess.TimeoutExpired:
            keyboard.terminate()
            keyboard.wait(timeout=3)
        result['keyboard_exit'] = keyboard.returncode
    os.close(master)
    os.close(slave)
    node.destroy_node()
    rclpy.shutdown()
    print('CP21_REMOTE_KEYBOARD_CLOUD ' + json.dumps(result), flush=True)
