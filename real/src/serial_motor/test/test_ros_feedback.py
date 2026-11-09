"""Verify actual ROS delivery of measured feedback with all serial access disabled."""

import math
import time

import pytest
import rclpy
from nav_msgs.msg import Odometry
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import JointState
from serial_motor.motor_driver import MotorDriver
from tf2_msgs.msg import TFMessage


def test_measured_pose_joint_and_tf_delivery():
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
    driver = None
    observer = None
    executor = SingleThreadedExecutor()
    try:
        driver = MotorDriver()
        driver.encoder_timer.cancel()
        driver.timeout_timer.cancel()
        observer = Node('cp21_feedback_observer')
        received = {'odom': [], 'joints': [], 'tf': []}
        observer.create_subscription(Odometry, '/fastbot/odom', received['odom'].append, 10)
        observer.create_subscription(
            JointState, '/fastbot/joint_states', received['joints'].append, 10
        )
        observer.create_subscription(TFMessage, '/tf', received['tf'].append, 10)
        executor.add_node(driver)
        executor.add_node(observer)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and driver.odom_pub_.get_subscription_count() < 1:
            executor.spin_once(timeout_sec=0.05)
        assert driver.odom_pub_.get_subscription_count() == 1
        driver.update_encoder_speed_sample(0, 0, 1.0)
        speeds = driver.update_encoder_speed_sample(100, 300, 1.2)
        driver.publish_odometry(speeds)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not all(received.values()):
            executor.spin_once(timeout_sec=0.05)
        assert all(received.values()), received
        message = received['odom'][0]
        assert message.pose.pose.position.x == pytest.approx(0.02 * math.pi)
        assert message.pose.pose.position.y == 0.0
        assert message.twist.twist.linear.x == pytest.approx(0.1 * math.pi)
        assert message.twist.twist.angular.z == pytest.approx(math.pi / 2)
        assert message.pose.pose.orientation.z == pytest.approx(math.sin(math.pi / 20))
        assert message.pose.pose.orientation.w == pytest.approx(math.cos(math.pi / 20))
        joint = received['joints'][0]
        assert joint.position == pytest.approx([0.2 * math.pi, 0.6 * math.pi])
        transforms = [
            t
            for group in received['tf']
            for t in group.transforms
            if t.child_frame_id == 'fastbot_base_link'
        ]
        assert len(transforms) == 1
        assert transforms[0].transform.rotation == message.pose.pose.orientation
        assert transforms[0].header.stamp == message.header.stamp
        assert driver.connection is None
    finally:
        executor.shutdown()
        if observer is not None:
            observer.destroy_node()
        if driver is not None:
            driver.destroy_node()
        rclpy.shutdown()
