"""Exercise complete measured-feedback intervals without opening a serial device."""

import math

import pytest
import rclpy
from geometry_msgs.msg import Twist
from serial_motor.motor_driver import MotorDriver


class Transport:
    def __init__(self):
        self.reply = b'0 0\r\n'
        self.commands = []

    def write(self, payload):
        self.commands.append(payload)
        return len(payload)

    def readline(self):
        return self.reply


class Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


@pytest.fixture
def node():
    rclpy.init(
        args=[
            '--ros-args',
            '-p',
            'wheel_radius:=0.05',
            '-p',
            'wheel_separation:=0.2',
            '-p',
            'encoder_cpr:=1000',
            '-p',
            'loop_rate:=30',
        ]
    )
    instance = MotorDriver(connection=Transport())
    instance.encoder_timer.cancel()
    instance.timeout_timer.cancel()
    for name in ('odom_pub_', 'joint_pub_', 'motor_vel_pub_', 'encoder_pub_'):
        setattr(instance, name, Publisher())
    transforms = []
    instance.tf_broadcaster.sendTransform = transforms.append
    instance.recorded_transforms = transforms
    yield instance
    instance.destroy_node()
    rclpy.shutdown()


def test_first_sample_does_not_invent_motion(node):
    assert node.update_encoder_speed_sample(200, 300, 10.0) is None
    assert (node.x, node.y, node.heading) == (0.0, 0.0, 0.0)
    assert node.odom_pub_.messages == []


def test_turn_then_drive_then_reverse_accumulates(node):
    node.update_encoder_speed_sample(0, 0, 10.0)
    # Opposite wheel travel: zero translation, positive quarter turn.
    node.update_encoder_speed_sample(-500, 500, 11.0)
    assert node.heading == pytest.approx(math.pi / 2)
    node.update_encoder_speed_sample(500, 1500, 13.0)
    assert node.x == pytest.approx(0.0, abs=1e-12)
    assert node.y == pytest.approx(0.1 * math.pi)
    # A reverse half revolution cancels half the translation, not the heading.
    speeds = node.update_encoder_speed_sample(0, 1000, 13.5)
    node.publish_odometry(speeds)
    assert node.y == pytest.approx(0.05 * math.pi)
    message = node.odom_pub_.messages[-1]
    assert message.twist.twist.linear.x == pytest.approx(-0.1 * math.pi)
    assert message.twist.twist.angular.z == pytest.approx(0.0)
    assert message.header.frame_id == 'fastbot_odom'
    assert message.child_frame_id == 'fastbot_base_link'
    assert message.pose.pose.orientation.z == pytest.approx(math.sin(math.pi / 4))
    assert message.pose.pose.orientation.w == pytest.approx(math.cos(math.pi / 4))
    tf = node.recorded_transforms[-1]
    assert tf.header == message.header
    assert tf.transform.translation.y == message.pose.pose.position.y
    assert tf.transform.rotation == message.pose.pose.orientation
    assert node.joint_pub_.messages[-1].name == [
        'fastbot_left_wheel_joint',
        'fastbot_right_wheel_joint',
    ]


@pytest.mark.parametrize('time', [10.0, 9.0, float('nan'), float('inf')])
def test_invalid_interval_does_not_advance_state(node, time):
    node.update_encoder_speed_sample(0, 0, 10.0)
    with pytest.raises(ValueError):
        node.update_encoder_speed_sample(100, 200, time)
    assert node.previous_encoder_sample == (0, 0, 10.0)
    assert (node.x, node.y, node.heading) == (0.0, 0.0, 0.0)


def test_wraparound_is_small_physical_motion(node):
    node.update_encoder_speed_sample(2147483640, -2147483640, 1.0)
    result = node.update_encoder_speed_sample(-2147483646, 2147483646, 2.0)
    assert result == pytest.approx((0.02 * math.pi, -0.02 * math.pi))
    assert node.x == pytest.approx(0.0)
    assert node.heading < 0


def test_protocol_timer_publishes_only_complete_intervals(node, monkeypatch):
    clock = iter([1.0, 1.2, 1.6])
    monkeypatch.setattr('serial_motor.motor_driver.time.monotonic', lambda: next(clock))
    for reply in (b'0 0\r\n', b'100 100\r\n', b'300 300\r\n'):
        node.connection.reply = reply
        node.publish_encoder_values()
    assert len(node.encoder_pub_.messages) == 3
    assert len(node.odom_pub_.messages) == 2
    assert len(node.motor_vel_pub_.messages) == 2
    assert node.x == pytest.approx(0.03 * math.pi)
    assert node.connection.commands == [b'e\r'] * 3


def test_bad_feedback_latches_fault_and_freezes_pose(node):
    node.connection.reply = b'123 incomplete'
    node.publish_encoder_values()
    assert node.communication_fault
    command_count = len(node.connection.commands)
    request = Twist()
    request.linear.x = 0.1
    node.cmd_vel_callback(request)
    node.publish_encoder_values()
    assert len(node.connection.commands) == command_count
    assert node.odom_pub_.messages == []


def test_nan_command_does_not_refresh_deadline(node):
    request = Twist()
    request.linear.x = float('nan')
    node.last_command_time = 12.0
    node.cmd_vel_callback(request)
    assert node.last_command_time == 12.0
    assert node.connection.commands == []


def test_valid_command_and_timeout_stop(node, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr('serial_motor.motor_driver.time.monotonic', lambda: clock[0])
    node.connection.reply = b'OK\r\n'
    request = Twist()
    request.linear.x = 0.1
    node.cmd_vel_callback(request)
    assert node.connection.commands == [b'm 10 10\r']
    clock[0] += 0.6
    node.check_command_timeout()
    assert node.connection.commands[-1] == b'm 0 0\r'
    assert node.last_command_time is None
