"""Run the reviewed vendor diagnostics and retain only sanitized output."""

from pathlib import Path
import os
import re
import subprocess

cache = Path.home() / '.cache/cp21-delegated'
cache.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.update(
    {
        'RMW_IMPLEMENTATION': 'rmw_cyclonedds_cpp',
        'CYCLONEDDS_URI': 'file:///var/lib/theconstruct.rrl/cyclonedds_husarnet.xml',
        'FASTRTPS_DEFAULT_PROFILES_FILE': '/var/lib/theconstruct.rrl/fastdds_husarnet.xml',
        'ROS_LOCALHOST_ONLY': '0',
    }
)
env.pop('ROS_DOMAIN_ID', None)
stop = subprocess.run(
    ['ros2', 'daemon', 'stop'], env=env, capture_output=True, text=True, timeout=15
)
print('DAEMON_STOP', stop.returncode, stop.stdout.strip())
check = subprocess.run(
    ['/usr/local/bin/theconstruct-doctor'],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    timeout=55,
)
clean = []
for line in check.stdout.splitlines():
    line = re.sub(r'\x1b\[[0-9;]*m', '', line)
    if re.search(r'(?i)token|secret|password|join.?code|authorization|api.?key', line):
        continue
    line = re.sub(r'https?://\S+', '[URL]', line)
    line = re.sub(r'(?:[0-9a-fA-F]{0,4}:){3,}[0-9a-fA-F:]+', '[network-address]', line)
    line = re.sub(r'[A-Za-z0-9_-]{32,}', '[identifier]', line)
    clean.append(line)
output = '\n'.join(clean) + '\n'
(cache / 'rrl-doctor-sanitized.log').write_text(output)
print('DOCTOR_EXIT', check.returncode)
print(output)
