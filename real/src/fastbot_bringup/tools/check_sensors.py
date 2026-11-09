"""Bounded real sensor streaming check; motor serial access stays disabled."""

import json
import math
import os
import re
from pathlib import Path
import signal
import subprocess
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, LaserScan

cache = Path.home() / '.cache/cp21-delegated'
cache.mkdir(parents=True, exist_ok=True)
log = cache / 'sensor-launch.log'
result = {'motor_serial_enabled': False, 'images': 0, 'scans': 0}
process = None
node = None
image_times = []
scan_times = []
try:
    rclpy.init()
    node = Node('cp21_sensor_probe')

    def image(message):
        result['images'] += 1
        image_times.append(time.monotonic())
        result['last_image'] = {
            'width': message.width,
            'height': message.height,
            'encoding': message.encoding,
            'frame': message.header.frame_id,
            'bytes': len(message.data),
            'step': message.step,
            'stamp_sec': message.header.stamp.sec,
            'sample_min': min(message.data) if message.data else None,
            'sample_max': max(message.data) if message.data else None,
        }

    def scan(message):
        result['scans'] += 1
        scan_times.append(time.monotonic())
        finite = [v for v in message.ranges if math.isfinite(v)]
        result['last_scan'] = {
            'rays': len(message.ranges),
            'finite_rays': len(finite),
            'frame': message.header.frame_id,
            'stamp_sec': message.header.stamp.sec,
            'angle_increment': message.angle_increment,
            'range_min': message.range_min,
            'range_max': message.range_max,
            'nearest': min(finite) if finite else None,
        }

    node.create_subscription(Image, '/fastbot_camera/image_raw', image, qos_profile_sensor_data)
    node.create_subscription(LaserScan, '/fastbot/scan', scan, qos_profile_sensor_data)
    with log.open('w') as output:
        process = subprocess.Popen(
            [
                'ros2',
                'launch',
                'fastbot_bringup',
                'bringup.launch.xml',
                'serial_enabled:=false',
                'camera_enabled:=true',
                'lidar_enabled:=true',
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if process.poll() is not None:
                raise RuntimeError('Sensor launch exited early')
            if result['images'] >= 30 and result['scans'] >= 20:
                break
        result['image_hz'] = (
            (len(image_times) - 1) / (image_times[-1] - image_times[0])
            if len(image_times) > 1
            else None
        )
        result['scan_hz'] = (
            (len(scan_times) - 1) / (scan_times[-1] - scan_times[0])
            if len(scan_times) > 1
            else None
        )
        assert result['images'] >= 10, 'No sustained camera stream'
        assert result['scans'] >= 10, 'No sustained laser stream'
        frame = result['last_image']
        assert (frame['width'], frame['height']) == (320, 240)
        assert frame['bytes'] >= frame['step'] * frame['height'] > 0
        assert frame['frame'] == 'fastbot_camera_optical_frame'
        assert frame['stamp_sec'] > 0
        laser = result['last_scan']
        assert laser['rays'] > 100 and laser['finite_rays'] > 0
        assert laser['angle_increment'] > 0
        assert laser['frame'] == 'fastbot_laser_link' and laser['stamp_sec'] > 0
        assert 'Serial controller ready' not in log.read_text()
        result['result'] = 'PASS'
except Exception as error:
    result['result'] = 'FAIL'
    result['error'] = repr(error)
    raise
finally:
    if process is not None and process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            result['forced_cleanup'] = True
    result['launch_exit_code'] = process.returncode if process is not None else None
    result['abnormal_child_exits'] = re.findall(
        r'process has died .*?exit code (-?\d+)', log.read_text()
    )
    if result['abnormal_child_exits'] or result.get('forced_cleanup'):
        result['result'] = 'FAIL'
        result['cleanup_error'] = 'At least one child did not exit normally'
    if node is not None:
        node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
    (cache / 'sensor-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
assert process.returncode == 0 and not result.get('forced_cleanup'), result
assert result['result'] == 'PASS', result
