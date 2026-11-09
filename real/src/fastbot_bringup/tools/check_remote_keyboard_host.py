"""One bounded keyboard i/k pulse; fake default, explicit approval before real use."""

import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import SingleThreadedExecutor
from serial_motor import motor_driver
from serial_motor_msgs.msg import EncoderVals, MotorVels
from std_msgs.msg import String

mode = os.environ.get('CP21_REMOTE_MODE', 'fake')
assert mode in ('fake', 'real')
root = Path.home() / '.local/share/cp21/arduino-nano-1.5.1'
port = '/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0'
events = []
connections = []
counts = []
velocities = []
remote_commands = []


class FakeSerial:
    def __init__(self, **kwargs):
        self.port = kwargs['port']
        self.is_open = False
        self.pending = None
        self.values = [0.0, 0.0]
        self.target = [0, 0]
        self.stamp = time.monotonic()

    def advance(self):
        now = time.monotonic()
        for index in (0, 1):
            self.values[index] += self.target[index] * 30 * (now - self.stamp)
        self.stamp = now

    def open(self):
        self.is_open = True

    def reset_input_buffer(self):
        self.pending = None

    def write(self, payload):
        assert self.pending is None
        self.advance()
        if payload == b'b\r':
            self.pending = b'57600\r\n'
        elif payload == b'e\r':
            self.pending = f'{int(self.values[0])} {int(self.values[1])}\r\n'.encode()
        else:
            parts = payload.decode().split()
            assert parts[0] == 'm'
            self.target = [int(parts[1]), int(parts[2])]
            self.pending = b'OK\r\n'
        return len(payload)

    def readline(self):
        result = self.pending
        self.pending = None
        if (
            os.environ.get('CP21_FAKE_FEEDBACK_LOSS') == '1'
            and any(self.target)
            and result not in (b'OK\r\n', b'57600\r\n')
        ):
            raise OSError('Injected fake encoder feedback loss')
        return result

    def close(self):
        self.is_open = False


if mode == 'real':
    real_port = Path(port).resolve(strict=True)
    sysfs = (Path('/sys/class/tty') / real_port.name / 'device').resolve()
    assert any(
        (parent / 'idVendor').exists()
        and (parent / 'idVendor').read_text().strip() == '1a86'
        and (parent / 'idProduct').read_text().strip() == '7523'
        for parent in sysfs.parents
    )
    users = subprocess.run(
        ['fuser', str(real_port)],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    assert users.returncode == 1
    factory = motor_driver.serial.Serial
else:
    factory = FakeSerial


class GuardedConnection:
    def __init__(self, **kwargs):
        kwargs['exclusive'] = True
        self.actual = factory(**kwargs)
        self.motion_time = None
        self.zero_time = None
        connections.append(self)

    def __getattr__(self, name):
        return getattr(self.actual, name)

    @property
    def port(self):
        return self.actual.port

    @port.setter
    def port(self, value):
        assert value == port
        self.actual.port = value

    def write(self, payload):
        if payload not in (b'b\r', b'e\r', b'm 12 12\r', b'm 0 0\r'):
            raise RuntimeError('Serial frame outside approved one-pulse scope')
        now = time.monotonic()
        if payload == b'm 12 12\r':
            if self.motion_time is not None:
                raise RuntimeError('A second nonzero command is forbidden')
            self.motion_time = now
        elif payload == b'm 0 0\r' and self.motion_time is not None:
            if self.zero_time is None:
                self.zero_time = now
        written = self.actual.write(payload)
        events.append({'write': payload.decode(), 'time': now, 'written': written})
        return written

    def readline(self):
        value = self.actual.readline()
        events.append({'read_hex': value.hex()})
        return value

    def close(self):
        self.actual.close()
        events.append({'closed': not self.actual.is_open})


topic = os.environ['CP21_REMOTE_TOPIC']
assert topic.startswith('/cp21_remote_')
report = {'status': 'running', 'mode': mode, 'events': events}


# Keep the bounded stimulus, watchdog checks and cleanup in one audited scope.
# This standalone test orchestrator intentionally exceeds the 50-statement guide.
def bounded_spin(node):  # noqa: PLR0915
    executor = SingleThreadedExecutor()
    probe = None
    ready = None
    try:
        probe = rclpy.create_node('cp21_bounded_motion_probe')
        ready = probe.create_publisher(String, topic + '/ready', 10)
        probe.create_subscription(
            Twist,
            topic,
            lambda msg: remote_commands.append((msg.linear.x, msg.angular.z, time.monotonic())),
            10,
        )
        probe.create_subscription(
            EncoderVals,
            '/fastbot/encoder_vals',
            lambda message: counts.append((message.mot_1_enc_val, message.mot_2_enc_val)),
            10,
        )
        probe.create_subscription(
            MotorVels,
            '/fastbot/motor_vels',
            lambda message: velocities.append((message.mot_1_rad_sec, message.mot_2_rad_sec)),
            10,
        )
        executor.add_node(node)
        executor.add_node(probe)
        deadline = time.monotonic() + 80.0
        baseline = None
        print('REMOTE_HOST_WAITING', flush=True)
        try:
            while time.monotonic() < deadline:
                executor.spin_once(timeout_sec=0.02)
                connection = connections[0]
                stale = (
                    node.previous_encoder_sample is not None
                    and time.monotonic() - node.previous_encoder_sample[2] > 0.35
                )
                if node.communication_fault or stale:
                    raise RuntimeError('Feedback lost or driver faulted')
                assert node.count_publishers(topic) <= 1, 'Competing command publishers'
                if connection.motion_time is None:
                    assert node.count_publishers(topic) <= 1, 'Competing command publishers'
                    if len(counts) >= 3 and node.count_publishers(topic) == 1:
                        assert len(set(counts[-3:])) == 1, 'Wheels moving before pulse'
                        baseline = counts[-1]
                        ready.publish(String(data='READY'))
                    continue
                if (
                    connection.zero_time is None
                    and time.monotonic() - connection.motion_time > 0.65
                ):
                    motor_driver.send_motor_command(connection, 'm 0 0\r')
                    raise RuntimeError('Harness fallback zero')
                if (
                    connection.zero_time is not None
                    and time.monotonic() - connection.zero_time > 2.0
                ):
                    break
        finally:
            connection = connections[0]
            if connection.motion_time is not None and connection.zero_time is None:
                motor_driver.send_motor_command(connection, 'm 0 0\r')
        connection = connections[0]
        assert connection.motion_time is not None and connection.zero_time is not None
        delay = connection.zero_time - connection.motion_time
        assert 0.0 < delay < 0.65, delay
        assert len(counts) >= 10 and len(velocities) >= 8
        assert len(set(counts[-5:])) == 1, 'Counts still changing at end'
        assert all(pair == (0.0, 0.0) for pair in velocities[-5:]), 'Speed not zero at end'
        delta = tuple(counts[-1][index] - baseline[index] for index in (0, 1))
        report.update(
            count_delta=delta,
            stop_delay=delay,
            stop_path='review_driver_log_for_cause',
            remote_commands=remote_commands,
            peak_rad_sec=tuple(max(v[index] for v in velocities) for index in (0, 1)),
            final_counts=counts[-5:],
            final_velocities=velocities[-5:],
            encoder_messages=len(counts),
            velocity_messages=len(velocities),
        )
        report['status'] = 'pass' if all(value > 0 for value in delta) else 'needs_review'
    finally:
        executor.remove_node(node)
        if probe is not None:
            executor.remove_node(probe)
            probe.destroy_node()
        executor.shutdown()
    raise KeyboardInterrupt


args = ['--ros-args']
for name, value in (
    ('wheel_radius', '0.032'),
    ('wheel_separation', '0.12'),
    ('encoder_cpr', '2537'),
    ('loop_rate', '30'),
    ('serial_enabled', 'true'),
    ('serial_port', port),
    ('baud_rate', '57600'),
    ('serial_read_timeout', '0.2'),
    ('serial_write_timeout', '0.2'),
    ('max_counts_per_loop', '15.0'),
    ('command_timeout', '0.5'),
):
    args.extend(('-p', name + ':=' + value))
args.extend(('-r', 'cmd_vel:=' + topic))
try:
    with (
        patch.object(motor_driver.serial, 'Serial', GuardedConnection),
        patch.object(motor_driver.rclpy, 'spin', side_effect=bounded_spin),
    ):
        motor_driver.main(args=args)
    assert len(connections) == 1 and not connections[0].actual.is_open and not rclpy.ok()
    writes = [e['write'] for e in events if 'write' in e]
    assert writes.count('m 12 12\r') == 1 and writes[-1] == 'm 0 0\r'
    report['nonzero_command_count'] = 1
    report['closed'] = True
except BaseException as error:
    report['status'] = 'failed'
    report['error'] = repr(error)
    raise
finally:
    for connection in connections:
        connection.close()
    if rclpy.ok():
        rclpy.shutdown()
    (root / f'remote-keyboard-{mode}-result.json').write_text(json.dumps(report, indent=2))
    print(
        json.dumps({k: v for k, v in report.items() if k != 'events'}, indent=2),
        flush=True,
    )
