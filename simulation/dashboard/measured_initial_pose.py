import json, math, os, time, rclpy
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data

reference = json.loads(os.environ['CP23_MAP_REFERENCE'])
rclpy.init()
node = rclpy.create_node('cp23_measured_spawn_in_saved_map')
last = None
count = 0


def cb(msg):
    global last, count
    last = msg
    count += 1


node.create_subscription(Odometry, '/fastbot/odom', cb, qos_profile_sensor_data)
end = time.monotonic() + 60
while time.monotonic() < end and count < 40:
    rclpy.spin_once(node, timeout_sec=0.1)
if last is None or count < 40:
    raise RuntimeError('Missing settled actual odometry')
p = last.pose.pose
q = p.orientation
yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
rotation = reference['map_to_world_rotation']
c, s = math.cos(rotation), math.sin(rotation)
old = reference['odom_pose']
mp = reference['map_pose']
dx = p.position.x - old['x']
dy = p.position.y - old['y']
result = {
    'x': mp['x'] + c * dx + s * dy,
    'y': mp['y'] - s * dx + c * dy,
    'yaw': math.atan2(math.sin(yaw - rotation), math.cos(yaw - rotation)),
    'source': 'Observed fresh spawn odometry transformed through saved actual map-to-world calibration',
    'odom': {'x': p.position.x, 'y': p.position.y, 'yaw': yaw},
    'samples': count,
}
print(json.dumps(result, indent=2))
node.destroy_node()
rclpy.shutdown()
