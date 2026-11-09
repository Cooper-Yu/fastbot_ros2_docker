"""Drive the installed keyboard app through a PTY on a hardware-free random topic."""

import json
import os
from pathlib import Path
import pty
import subprocess
import time
import uuid

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node

cache = Path.home() / '.cache/cp21-delegated'
cache.mkdir(parents=True, exist_ok=True)
topic = '/cp21_keyboard_probe_' + uuid.uuid4().hex[:12]
received = []
process = None
node = None
master, slave = pty.openpty()
result = {'hardware_enabled': False, 'topic': topic}
try:
    rclpy.init()
    node = Node('cp21_keyboard_probe')
    node.create_subscription(
        Twist, topic, lambda msg: received.append((msg.linear.x, msg.angular.z)), 10
    )
    with (cache / 'keyboard.log').open('w') as log:
        process = subprocess.Popen(
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
            start_new_session=True,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and node.count_publishers(topic) != 1:
            rclpy.spin_once(node, timeout_sec=0.05)
        assert node.count_publishers(topic) == 1
        # Allow terminal setup and subscriber discovery before pressing a key.
        until = time.monotonic() + 0.5
        while time.monotonic() < until:
            rclpy.spin_once(node, timeout_sec=0.05)
        for key, expected in [(b'i', (0.03, 0.0)), (b'j', (0.0, 0.3)), (b'k', (0.0, 0.0))]:
            start = len(received)
            os.write(master, key)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and expected not in received[start:]:
                rclpy.spin_once(node, timeout_sec=0.05)
            assert expected in received[start:], (key, received)
        os.write(master, b'\x03')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and process.poll() is None:
            rclpy.spin_once(node, timeout_sec=0.05)
        assert process.poll() == 0, process.poll()
        result.update(
            {'result': 'PASS', 'received_twists': received, 'exit_code': process.returncode}
        )
finally:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, 9)
            process.wait(timeout=3)
    os.close(master)
    os.close(slave)
    if node is not None:
        node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
    (cache / 'keyboard-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
