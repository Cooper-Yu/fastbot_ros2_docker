"""Bounded launch/topic/cleanup smoke test with every hardware path disabled."""

from pathlib import Path
import json
import os
import signal
import subprocess
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node

cache = Path.home() / '.cache/cp21-delegated'
cache.mkdir(parents=True, exist_ok=True)
log = cache / 'preview-launch.log'
result = {'hardware_enabled': False}
process = None
observer = None
try:
    rclpy.init()
    observer = Node('cp21_launch_probe')
    publisher = observer.create_publisher(Twist, '/fastbot/cmd_vel', 10)
    with log.open('w') as output:
        process = subprocess.Popen(
            [
                'ros2',
                'launch',
                'fastbot_bringup',
                'bringup.launch.xml',
                'serial_enabled:=false',
                'lidar_enabled:=false',
                'camera_enabled:=false',
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            rclpy.spin_once(observer, timeout_sec=0.1)
            names = observer.get_node_names_and_namespaces()
            if ('motor_driver', '/fastbot') in names and publisher.get_subscription_count() == 1:
                break
            if process.poll() is not None:
                raise RuntimeError('Preview exited before discovery: ' + log.read_text())
        else:
            raise TimeoutError('Motor subscriber not discovered')
        topics = dict(observer.get_topic_names_and_types())
        for topic in ('/fastbot/odom', '/fastbot/joint_states', '/fastbot/robot_description'):
            assert topic in topics, topic
        request = Twist()
        request.linear.x = 0.02
        publisher.publish(request)
        until = time.monotonic() + 1.5
        while time.monotonic() < until:
            rclpy.spin_once(observer, timeout_sec=0.05)
        text = log.read_text()
        assert 'Motor command preview:' in text, text
        assert 'Timeout stop preview:' in text, text
        assert 'Serial controller ready' not in text
        assert 'got segment fastbot_base_link' in text, text
        result['graph_topics'] = sorted(topics)
        result['command_and_timeout_preview'] = True
finally:
    if process is not None and process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            result['forced_cleanup'] = True
    if observer is not None:
        observer.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
assert process.returncode == 0, (process.returncode, log.read_text())
assert not result.get('forced_cleanup'), result
result.update({'result': 'PASS', 'launch_exit_code': process.returncode})
Path.home().joinpath('.cache/cp21-delegated/preview-launch-result.json').write_text(
    json.dumps(result, indent=2) + '\n'
)
print(json.dumps(result))
