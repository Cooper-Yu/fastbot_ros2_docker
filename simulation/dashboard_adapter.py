#!/usr/bin/env python3
"""Guarded command and action boundary for the independent FastBot reference.

Topic contract, with configurable names:
  manual_cmd: geometry_msgs/Twist, hold at 10 Hz; zero explicitly releases.
  goal: geometry_msgs/PoseStamped in map_frame; stamp identifies the request.
  cancel: std_msgs/Empty, cancel the current browser or public action request.
  pose: geometry_msgs/PoseStamped from fresh map-to-base TF only.
  status: std_msgs/String containing JSON, republished on a steady-clock timer.

Status includes request_id, state, goal_uuid, result, diagnostic, owner,
feedback_valid, pose_valid, navigation_ready, manual_allowed and cancel_requested.
States are idle, awaiting_acceptance, accepted, executing, cancel_requested,
canceled, rejected, succeeded, aborted and unavailable. Additional readiness fields
must be checked even when the most recent request has a terminal state.

Public /navigate_to_pose is a proxy, not Nav2's backend action. RViz and browser
requests share one reservation before backend submission. Backend action endpoints
and nav command topics are internal deployment interfaces, not browser APIs.
Unexpected backend action activity blocks output rather than granting ownership.
No transport provides authorization: audit ROS publishers/clients in cloud before
motion. Do not run SLAM and navigation launches concurrently.

Fresh odometry, scan receipt, source stamps and odom-to-base TF gate all motion.
Navigation also requires fresh map-to-base TF. Manual mapping does not require an
already-created map. Watchdogs use monotonic time and a steady-clock timer even
when /clock pauses. Sensor/TF gaps pause output while retaining the same active
backend goal; stable fresh feedback permits new commands for that goal. Clock
resets, explicit cancellation and unknown ownership never auto-resume a goal.
No pose is published for unavailable or stale map TF; status marks it invalid.
"""

import copy
import json
import math
import signal
import time
import uuid

import rclpy
from action_msgs.msg import GoalStatus, GoalStatusArray
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry, OccupancyGrid
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.clock import Clock, ClockType
from rclpy.duration import Duration
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.task import Future
from rclpy.time import Time
from rclpy.signals import SignalHandlerOptions
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Empty, String
from tf2_ros import Buffer, TransformException, TransformListener


ACTIVE = {GoalStatus.STATUS_ACCEPTED, GoalStatus.STATUS_EXECUTING, GoalStatus.STATUS_CANCELING}
TERMINAL = {
    GoalStatus.STATUS_SUCCEEDED: 'succeeded',
    GoalStatus.STATUS_CANCELED: 'canceled',
    GoalStatus.STATUS_ABORTED: 'aborted',
}


def uuid_text(identifier):
    return bytes(identifier.uuid).hex()


def finite(values):
    return all(math.isfinite(float(value)) for value in values)


def odom_delta(previous, current):
    """Velocity estimate from measured odometry poses and source seconds."""
    if previous is None:
        return None
    dt = current[0] - previous[0]
    if not 1.0e-5 < dt <= 1.0:
        return None
    dx, dy = current[1] - previous[1], current[2] - previous[2]
    yaw = previous[3]
    angle = current[3] - yaw
    return (
        (dx * math.cos(yaw) + dy * math.sin(yaw)) / dt,
        (-dx * math.sin(yaw) + dy * math.cos(yaw)) / dt,
        math.atan2(math.sin(angle), math.cos(angle)) / dt,
    )


def source_advances(stamp, previous):
    """A late/duplicate packet never overwrites a newer real sample or renews its age."""
    return previous is None or (stamp.sec, stamp.nanosec) > (previous.sec, previous.nanosec)


def planar_command(message, linear_limit, angular_limit):
    values = [
        message.linear.x,
        message.linear.y,
        message.linear.z,
        message.angular.x,
        message.angular.y,
        message.angular.z,
    ]
    if not finite(values):
        raise ValueError('Nonfinite Twist rejected')
    if any(
        abs(value) > 1.0e-6
        for value in (message.linear.y, message.linear.z, message.angular.x, message.angular.y)
    ):
        raise ValueError('Only planar linear.x and angular.z are supported')
    command = Twist()
    command.linear.x = max(-linear_limit, min(linear_limit, message.linear.x))
    command.angular.z = max(-angular_limit, min(angular_limit, message.angular.z))
    return command


def moving(command):
    return abs(command.linear.x) > 1.0e-6 or abs(command.angular.z) > 1.0e-6


class WebAdapter(Node):
    def __init__(self):
        super().__init__('web_adapter')
        defaults = {
            'navigation_enabled': True,
            'map_frame': 'map',
            'odom_frame': 'fastbot_1_odom',
            'base_frame': 'fastbot_1_base_link',
            'scan_topic': '/fastbot_1/scan',
            'odom_topic': '/fastbot_1/odom',
            'measured_odom_topic': '/fastbot_web/measured_odom',
            'cmd_vel_topic': '/fastbot_1/cmd_vel',
            'manual_topic': '/fastbot_web/manual_cmd',
            'goal_topic': '/fastbot_web/goal',
            'cancel_topic': '/fastbot_web/cancel',
            'status_topic': '/fastbot_web/status',
            'pose_topic': '/fastbot_web/pose',
            'nav_cmd_topic': '/fastbot_web/nav_cmd',
            'public_action': '/navigate_to_pose',
            'backend_action': '/fastbot_nav/navigate_to_pose',
            'backend_through_action': '/fastbot_nav/navigate_through_poses',
            'manual_timeout': 0.3,
            'nav_timeout': 0.3,
            'feedback_timeout': 0.5,
            'transform_timeout': 0.5,
            'linear_limit': 0.15,
            'angular_limit': 0.6,
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        self.settings = {name: self.get_parameter(name).value for name in defaults}
        for name in ('manual_timeout', 'nav_timeout', 'feedback_timeout', 'transform_timeout'):
            value = float(self.settings[name])
            if not math.isfinite(value) or value <= 0.0 or value > 0.5:
                raise ValueError(name + ' must be positive and at most 0.5 seconds')
        for name, maximum in (('linear_limit', 0.15), ('angular_limit', 0.6)):
            value = float(self.settings[name])
            if not math.isfinite(value) or not 0.0 < value <= maximum:
                raise ValueError(name + ' exceeds the permitted motion bound')
        command_names = [
            self.settings[name] for name in ('cmd_vel_topic', 'manual_topic', 'nav_cmd_topic')
        ]
        if len(set(command_names)) != 3 or any(not name.startswith('/') for name in command_names):
            raise ValueError(
                'Final, manual and navigation command topics must be distinct absolute names'
            )
        if self.settings['public_action'] == self.settings['backend_action']:
            raise ValueError('Public action cannot equal backend action')
        if self.settings['odom_topic'] == self.settings['measured_odom_topic']:
            raise ValueError(
                'Raw and derived odometry topics must differ to prevent feedback loops'
            )
        self.enabled = bool(self.settings['navigation_enabled'])
        self.owner = None
        self.request_id = None
        self.state = 'idle'
        self.result_code = None
        self.diagnostic = 'Waiting for measured feedback; no motion requested'
        self.backend_handle = None
        self.public_handle = None
        self.completion = None
        self.cancel_reason = None
        self.cancel_requested = False
        self.cancel_sent = False
        self.backend_started = False
        self.feedback_valid = False
        self.pose_valid = False
        self.navigation_paused = False
        self.pause_reason = None
        self.recovery_started = None
        self.previous_ros_time = None
        self.clock_reset = False
        self.manual_released = True
        self.manual_command = Twist()
        self.manual_received = -math.inf
        self.nav_command = Twist()
        self.nav_received = -math.inf
        self.nav_epoch = math.inf
        self.odom_received = -math.inf
        self.scan_received = -math.inf
        self.odom_valid = False
        self.scan_valid = False
        self.odom_stamp = None
        self.scan_stamp = None
        self.measured_stopped = False
        self.previous_odom_pose = None
        self.active_backend = set()
        self.active_through = set()
        self.last_status = -math.inf
        self.closed = False
        self.command_publisher = self.create_publisher(Twist, self.settings['cmd_vel_topic'], 1)
        self.measured_odom_publisher = self.create_publisher(
            Odometry, self.settings['measured_odom_topic'], 5
        )
        self.pose_publisher = self.create_publisher(PoseStamped, self.settings['pose_topic'], 5)
        # Coach CP23 support: re-emit the real latched map for late browser connections.
        self.web_map_publisher = self.create_publisher(OccupancyGrid, '/fastbot_web/map', 1)
        self.web_map = None
        self.create_subscription(
            OccupancyGrid,
            '/map',
            self.on_web_map,
            QoSProfile(
                depth=1,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                reliability=ReliabilityPolicy.RELIABLE,
            ),
        )
        self.map_timer = self.create_timer(
            1.0, self.publish_web_map, clock=Clock(clock_type=ClockType.STEADY_TIME)
        )
        self.status_publisher = self.create_publisher(String, self.settings['status_topic'], 5)
        self.tf_buffer = Buffer(cache_time=Duration(seconds=10.0))
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.backend = ActionClient(self, NavigateToPose, self.settings['backend_action'])
        status_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        # Non-motion echo validates the browser -> bridge -> ROS -> browser path.
        # It never reserves a goal, changes control ownership, or publishes velocity.
        self.control_echo = self.create_publisher(String, '/fastbot_web/control_pong', 1)
        self.create_subscription(String, '/fastbot_web/control_ping', self.on_control_ping, 1)
        self.create_subscription(Twist, self.settings['manual_topic'], self.on_manual, 1)
        self.create_subscription(Twist, self.settings['nav_cmd_topic'], self.on_nav_command, 1)
        self.create_subscription(PoseStamped, self.settings['goal_topic'], self.on_browser_goal, 5)
        self.create_subscription(Empty, self.settings['cancel_topic'], self.on_cancel, 5)
        newest_sensor = QoSProfile(
            depth=1, reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE
        )
        self.create_subscription(Odometry, self.settings['odom_topic'], self.on_odom, newest_sensor)
        self.create_subscription(
            LaserScan, self.settings['scan_topic'], self.on_scan, newest_sensor
        )
        self.create_subscription(
            GoalStatusArray,
            self.settings['backend_action'].rstrip('/') + '/_action/status',
            self.on_backend_status,
            status_qos,
        )
        self.create_subscription(
            GoalStatusArray,
            self.settings['backend_through_action'].rstrip('/') + '/_action/status',
            self.on_through_status,
            status_qos,
        )
        self.action_server = ActionServer(
            self,
            NavigateToPose,
            self.settings['public_action'],
            execute_callback=self.execute_public,
            goal_callback=self.accept_public,
            cancel_callback=self.cancel_public,
        )
        self.steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.timer = self.create_timer(0.05, self.tick, clock=self.steady_clock)
        self.zero()
        self.get_logger().info(
            'FastBot command boundary ready; initially stopped. Cloud calibration pending.'
        )

    def on_control_ping(self, message):
        if isinstance(message.data, str) and 1 <= len(message.data) <= 128:
            self.control_echo.publish(message)

    def zero(self):
        self.command_publisher.publish(Twist())

    def invalidate_commands(self):
        self.manual_command = Twist()
        self.manual_received = -math.inf
        self.nav_command = Twist()
        self.nav_received = -math.inf
        self.zero()

    def stamp_fresh(self, stamp, maximum):
        if stamp is None or (stamp.sec == 0 and stamp.nanosec == 0):
            return False
        age = (self.get_clock().now() - Time.from_msg(stamp)).nanoseconds / 1.0e9
        return -0.1 <= age <= maximum

    def on_odom(self, message):
        if not source_advances(message.header.stamp, self.odom_stamp):
            return
        self.odom_received = time.monotonic()
        self.odom_stamp = message.header.stamp
        twist = message.twist.twist
        self.odom_valid = (
            message.header.frame_id == self.settings['odom_frame']
            and message.child_frame_id == self.settings['base_frame']
            and finite(
                [
                    twist.linear.x,
                    twist.linear.y,
                    twist.linear.z,
                    twist.angular.x,
                    twist.angular.y,
                    twist.angular.z,
                ]
            )
        )
        position, rotation = message.pose.pose.position, message.pose.pose.orientation
        self.odom_valid = (
            self.odom_valid
            and finite(
                [position.x, position.y, position.z, rotation.x, rotation.y, rotation.z, rotation.w]
            )
            and abs(math.sqrt(rotation.x**2 + rotation.y**2 + rotation.z**2 + rotation.w**2) - 1.0)
            < 0.05
        )
        velocity = None
        if self.odom_valid:
            yaw = math.atan2(
                2 * (rotation.w * rotation.z + rotation.x * rotation.y),
                1 - 2 * (rotation.y**2 + rotation.z**2),
            )
            current = (
                message.header.stamp.sec + message.header.stamp.nanosec / 1.0e9,
                position.x,
                position.y,
                yaw,
            )
            velocity = odom_delta(self.previous_odom_pose, current)
            self.previous_odom_pose = current
        else:
            self.previous_odom_pose = None
        self.measured_stopped = bool(
            self.odom_valid
            and velocity is not None
            and math.hypot(velocity[0], velocity[1]) < 0.02
            and abs(velocity[2]) < 0.04
            and math.hypot(twist.linear.x, twist.linear.y) < 0.02
            and abs(twist.angular.z) < 0.04
        )
        if velocity is not None:
            measured = copy.deepcopy(message)
            measured.twist.twist.linear.x, measured.twist.twist.linear.y = velocity[:2]
            measured.twist.twist.angular.z = velocity[2]
            self.measured_odom_publisher.publish(measured)

    def on_web_map(self, message):
        self.web_map = message
        self.publish_web_map()

    def publish_web_map(self):
        if self.web_map is not None:
            self.web_map_publisher.publish(self.web_map)

    def on_scan(self, message):
        if not source_advances(message.header.stamp, self.scan_stamp):
            return
        self.scan_received = time.monotonic()
        self.scan_stamp = message.header.stamp
        self.scan_valid = bool(message.header.frame_id and message.ranges) and (
            finite(
                [
                    message.range_min,
                    message.range_max,
                    message.angle_min,
                    message.angle_max,
                    message.angle_increment,
                ]
            )
            and message.range_max > message.range_min >= 0.0
            and message.angle_increment != 0.0
            and any(
                math.isfinite(distance) and message.range_min <= distance <= message.range_max
                for distance in message.ranges
            )
        )

    def fresh_transform(self, target):
        try:
            transform = self.tf_buffer.lookup_transform(target, self.settings['base_frame'], Time())
        except TransformException:
            return None
        translation = transform.transform.translation
        rotation = transform.transform.rotation
        if not finite(
            [
                translation.x,
                translation.y,
                translation.z,
                rotation.x,
                rotation.y,
                rotation.z,
                rotation.w,
            ]
        ):
            return None
        norm = math.sqrt(
            sum(value * value for value in (rotation.x, rotation.y, rotation.z, rotation.w))
        )
        if norm < 1.0e-6 or abs(norm - 1.0) > 0.05:
            return None
        if not self.stamp_fresh(transform.header.stamp, self.settings['transform_timeout']):
            return None
        return transform

    def refresh_feedback(self):
        now = time.monotonic()
        maximum = self.settings['feedback_timeout']
        self.feedback_valid = bool(
            self.count_publishers(self.settings['cmd_vel_topic']) == 1
            and self.odom_valid
            and self.scan_valid
            and now - self.odom_received <= maximum
            and now - self.scan_received <= maximum
            and self.stamp_fresh(self.odom_stamp, maximum)
            and self.stamp_fresh(self.scan_stamp, maximum)
            and self.fresh_transform(self.settings['odom_frame']) is not None
        )
        transform = self.fresh_transform(self.settings['map_frame'])
        self.pose_valid = transform is not None and self.feedback_valid
        ros_now = self.get_clock().now().nanoseconds / 1.0e9
        if self.previous_ros_time is not None and ros_now < self.previous_ros_time - 0.1:
            self.clock_reset = True
        self.previous_ros_time = ros_now
        if self.clock_reset:
            self.feedback_valid = False
            self.pose_valid = False

        def age(stamp):
            return None if stamp is None else ros_now - stamp.sec - stamp.nanosec / 1.0e9

        self.feedback_detail = {
            'odom_source_age': age(self.odom_stamp),
            'scan_source_age': age(self.scan_stamp),
            'odom_receipt_age': None
            if not math.isfinite(self.odom_received)
            else now - self.odom_received,
            'scan_receipt_age': None
            if not math.isfinite(self.scan_received)
            else now - self.scan_received,
            'odom_valid': self.odom_valid,
            'scan_valid': self.scan_valid,
            'clock_reset': self.clock_reset,
            'odom_tf_fresh': self.fresh_transform(self.settings['odom_frame']) is not None,
            'map_tf_fresh': transform is not None,
        }
        if self.pose_valid:
            pose = PoseStamped()
            pose.header = copy.deepcopy(transform.header)
            pose.header.frame_id = self.settings['map_frame']
            pose.pose.position.x = transform.transform.translation.x
            pose.pose.position.y = transform.transform.translation.y
            pose.pose.position.z = transform.transform.translation.z
            pose.pose.orientation = copy.deepcopy(transform.transform.rotation)
            self.pose_publisher.publish(pose)

    def unknown_backend_activity(self):
        known = uuid_text(self.backend_handle.goal_id) if self.backend_handle is not None else None
        return bool(
            self.active_through or any(identifier != known for identifier in self.active_backend)
        )

    def backend_ready(self):
        return self.enabled and self.backend.server_is_ready()

    def manual_allowed(self):
        return self.feedback_valid and self.owner is None and not self.unknown_backend_activity()

    def on_manual(self, message):
        try:
            command = planar_command(
                message, self.settings['linear_limit'], self.settings['angular_limit']
            )
        except ValueError as error:
            self.manual_released = False
            self.invalidate_commands()
            self.diagnostic = str(error)
            return
        if not moving(command):
            self.manual_released = True
            self.manual_command = Twist()
            self.manual_received = -math.inf
            if self.owner is None:
                self.zero()
            return
        self.refresh_feedback()
        if not self.manual_allowed():
            self.manual_released = False
            self.manual_command = Twist()
            self.manual_received = -math.inf
            self.zero()
            self.diagnostic = (
                'Manual command blocked: navigation owns motion or feedback is unavailable'
            )
            return
        self.manual_released = False
        self.manual_command = command
        self.manual_received = time.monotonic()

    def on_nav_command(self, message):
        if (
            self.owner is None
            or self.backend_handle is None
            or self.cancel_requested
            or self.navigation_paused
        ):
            self.nav_command = Twist()
            self.nav_received = -math.inf
            return
        try:
            command = planar_command(
                message, self.settings['linear_limit'], self.settings['angular_limit']
            )
        except ValueError as error:
            self.diagnostic = str(error)
            self.request_cancel('Invalid Nav2 velocity command: ' + str(error))
            return
        self.nav_command = command
        self.nav_received = time.monotonic()

    def validate_pose(self, incoming):
        pose = copy.deepcopy(incoming)
        if pose.header.frame_id != self.settings['map_frame']:
            raise ValueError('Goal must use configured map_frame: ' + self.settings['map_frame'])
        position = pose.pose.position
        rotation = pose.pose.orientation
        if not finite(
            [position.x, position.y, position.z, rotation.x, rotation.y, rotation.z, rotation.w]
        ):
            raise ValueError('Goal contains nonfinite coordinates')
        norm = math.sqrt(
            sum(value * value for value in (rotation.x, rotation.y, rotation.z, rotation.w))
        )
        if norm < 1.0e-6:
            raise ValueError('Goal quaternion has zero norm')
        rotation.x /= norm
        rotation.y /= norm
        rotation.z /= norm
        rotation.w /= norm
        pose.header.stamp = self.get_clock().now().to_msg()
        return pose

    def reservation_error(self):
        self.refresh_feedback()
        if self.owner is not None or self.unknown_backend_activity():
            return 'Another navigation request is pending or active'
        if not self.backend_ready():
            return 'Nav2 backend unavailable or navigation disabled during mapping'
        if not self.feedback_valid or not self.pose_valid:
            return 'Fresh measured odometry, scan and localized map TF are required'
        if not self.manual_released or not self.measured_stopped:
            return 'Explicitly release manual control and wait for measured stop before navigation'
        return None

    def reserve(self, source, request_id):
        self.navigation_paused = False
        self.pause_reason = None
        self.recovery_started = None
        self.owner = source
        self.request_id = request_id
        self.state = 'awaiting_acceptance'
        self.result_code = None
        self.diagnostic = 'Navigation reserved; waiting for backend acceptance'
        self.backend_handle = None
        self.public_handle = None
        self.cancel_reason = None
        self.cancel_requested = False
        self.cancel_sent = False
        self.backend_started = False
        self.completion = Future()
        self.nav_epoch = time.monotonic()
        self.invalidate_commands()
        self.publish_status()

    def on_browser_goal(self, message):
        if self.owner is not None:
            self.diagnostic = 'Overlapping browser request rejected; current request remains active'
            self.publish_status()
            return
        stamp = message.header.stamp
        request_id = (
            f'{stamp.sec}:{stamp.nanosec}' if stamp.sec or stamp.nanosec else uuid.uuid4().hex
        )
        try:
            pose = self.validate_pose(message)
        except ValueError as error:
            self.request_id = request_id
            self.state = 'rejected'
            self.result_code = None
            self.diagnostic = str(error)
            self.publish_status()
            return
        reason = self.reservation_error()
        if reason is not None:
            self.request_id = request_id
            self.state = 'unavailable' if not self.backend_ready() else 'rejected'
            self.result_code = None
            self.diagnostic = reason
            self.publish_status()
            return
        self.reserve('browser', request_id)
        goal = NavigateToPose.Goal()
        goal.pose = pose
        self.start_backend(goal)

    def accept_public(self, request):
        try:
            self.validate_pose(request.pose)
        except ValueError as error:
            self.diagnostic = 'Public action rejected: ' + str(error)
            self.publish_status()
            return GoalResponse.REJECT
        reason = self.reservation_error()
        if reason is not None:
            self.diagnostic = 'Public action rejected: ' + reason
            self.publish_status()
            return GoalResponse.REJECT
        if request.behavior_tree:
            self.diagnostic = (
                'Public action rejects custom behavior trees; use configured Nav2 trees'
            )
            self.publish_status()
            return GoalResponse.REJECT
        self.reserve('action', uuid.uuid4().hex)
        return GoalResponse.ACCEPT

    async def execute_public(self, goal_handle):
        self.public_handle = goal_handle
        self.request_id = uuid_text(goal_handle.goal_id)
        goal = copy.deepcopy(goal_handle.request)
        goal.pose = self.validate_pose(goal.pose)
        if goal_handle.is_cancel_requested:
            self.cancel_requested = True
        completion = self.completion
        self.start_backend(goal)
        outcome = await completion
        code, result = outcome
        if code == GoalStatus.STATUS_SUCCEEDED:
            goal_handle.succeed()
        elif code == GoalStatus.STATUS_CANCELED and goal_handle.is_cancel_requested:
            goal_handle.canceled()
        else:
            goal_handle.abort()
        return result

    def cancel_public(self, goal_handle):
        if self.owner != 'action':
            return CancelResponse.REJECT
        if self.public_handle is not None and uuid_text(goal_handle.goal_id) != uuid_text(
            self.public_handle.goal_id
        ):
            return CancelResponse.REJECT
        self.request_cancel()
        return CancelResponse.ACCEPT

    def start_backend(self, goal):
        if self.backend_started:
            return
        if self.cancel_requested:
            self.finish(
                GoalStatus.STATUS_CANCELED,
                NavigateToPose.Result(),
                'Canceled before backend submission',
            )
            return
        if not self.backend.server_is_ready():
            self.finish(
                GoalStatus.STATUS_ABORTED,
                NavigateToPose.Result(),
                'Backend disappeared before submission',
            )
            return
        self.backend_started = True
        token = self.request_id
        try:
            future = self.backend.send_goal_async(goal, feedback_callback=self.on_action_feedback)
            future.add_done_callback(lambda completed: self.on_goal_response(completed, token))
        except Exception as error:
            self.diagnostic = 'Submission outcome uncertain; motion locked: ' + str(error)
            self.state = 'unavailable'
            self.zero()
            self.publish_status()

    def on_goal_response(self, future, token):
        if self.owner is None or token != self.request_id:
            return
        try:
            handle = future.result()
        except Exception as error:
            self.state = 'unavailable'
            self.diagnostic = 'Acceptance outcome uncertain; motion remains locked: ' + str(error)
            self.zero()
            self.publish_status()
            return
        if not handle.accepted:
            self.finish(
                GoalStatus.STATUS_ABORTED,
                NavigateToPose.Result(),
                'Backend rejected the goal',
                state='rejected',
            )
            return
        self.backend_handle = handle
        self.nav_epoch = time.monotonic()
        self.nav_received = -math.inf
        self.state = 'cancel_requested' if self.cancel_requested else 'accepted'
        self.diagnostic = 'Backend accepted goal'
        try:
            handle.get_result_async().add_done_callback(
                lambda completed: self.on_result(completed, token)
            )
        except Exception as error:
            self.state = 'unavailable'
            self.diagnostic = 'Result subscription failed; motion remains locked: ' + str(error)
            self.request_cancel('Result subscription failed: ' + str(error))
        if self.cancel_requested:
            self.send_backend_cancel()
        self.publish_status()

    def on_action_feedback(self, message):
        if self.backend_handle is None or uuid_text(message.goal_id) != uuid_text(
            self.backend_handle.goal_id
        ):
            return
        if not self.cancel_requested and self.state != 'unavailable':
            self.state = 'executing'
        if self.public_handle is not None and self.public_handle.is_active:
            self.public_handle.publish_feedback(message.feedback)

    def on_result(self, future, token):
        if self.owner is None or token != self.request_id:
            return
        try:
            wrapped = future.result()
        except Exception as error:
            self.state = 'unavailable'
            self.diagnostic = 'Terminal result unavailable; motion remains locked: ' + str(error)
            self.zero()
            self.publish_status()
            return
        if wrapped.status not in TERMINAL:
            self.state = 'unavailable'
            self.diagnostic = 'Nonterminal backend result; motion remains locked'
            self.zero()
            self.publish_status()
            return
        self.finish(wrapped.status, wrapped.result, 'Backend terminal action result received')

    def finish(self, code, result, diagnostic, state=None):
        completion = self.completion
        self.navigation_paused = False
        self.pause_reason = None
        self.recovery_started = None
        self.result_code = int(code)
        self.state = state or TERMINAL.get(code, 'aborted')
        self.diagnostic = diagnostic
        self.owner = None
        self.backend_started = False
        self.nav_epoch = math.inf
        self.manual_released = True
        self.invalidate_commands()
        self.publish_status()
        if completion is not None and not completion.done():
            completion.set_result((code, result))

    def on_cancel(self, unused):
        self.request_cancel()

    def request_cancel(self, reason='Explicit cancellation input'):
        self.navigation_paused = False
        self.pause_reason = None
        self.recovery_started = None
        self.invalidate_commands()
        if self.owner is None:
            self.diagnostic = 'Stopped; no owned navigation request to cancel'
            self.publish_status()
            return
        if not self.cancel_requested:
            self.cancel_reason = reason
            self.get_logger().warning(
                'Navigation cancellation: ' + reason + '; request=' + str(self.request_id)
            )
        self.cancel_requested = True
        self.state = 'cancel_requested'
        self.diagnostic = 'Cancellation requested; navigation lock held until terminal result'
        if self.backend_handle is not None:
            self.send_backend_cancel()
        self.publish_status()

    def send_backend_cancel(self):
        if self.cancel_sent or self.backend_handle is None:
            return
        self.cancel_sent = True
        try:
            self.backend_handle.cancel_goal_async().add_done_callback(self.on_cancel_response)
        except Exception as error:
            self.diagnostic = 'Cancellation delivery uncertain; motion locked: ' + str(error)
            self.publish_status()

    def on_cancel_response(self, future):
        try:
            response = future.result()
            if not response.goals_canceling and self.owner is not None:
                self.diagnostic = (
                    'Backend did not confirm cancellation; waiting for terminal result'
                )
        except Exception as error:
            if self.owner is not None:
                self.diagnostic = (
                    'Cancel response unavailable; waiting for terminal result: ' + str(error)
                )
        self.publish_status()

    def on_backend_status(self, message):
        self.active_backend = {
            uuid_text(entry.goal_info.goal_id)
            for entry in message.status_list
            if entry.status in ACTIVE
        }
        if (
            self.backend_handle is not None
            and not self.cancel_requested
            and self.state != 'unavailable'
        ):
            identifier = uuid_text(self.backend_handle.goal_id)
            for entry in message.status_list:
                if (
                    uuid_text(entry.goal_info.goal_id) == identifier
                    and entry.status == GoalStatus.STATUS_EXECUTING
                ):
                    self.state = 'executing'
        if self.unknown_backend_activity():
            self.invalidate_commands()
            self.diagnostic = 'Unexpected backend action client; output inhibited'

    def on_through_status(self, message):
        self.active_through = {
            uuid_text(entry.goal_info.goal_id)
            for entry in message.status_list
            if entry.status in ACTIVE
        }
        if self.active_through:
            self.invalidate_commands()
            self.diagnostic = 'Unowned NavigateThroughPoses activity; output inhibited'

    def publish_status(self):
        identifier = (
            uuid_text(self.backend_handle.goal_id) if self.backend_handle is not None else None
        )
        payload = {
            'request_id': self.request_id,
            'state': self.state,
            'goal_uuid': identifier,
            'result': self.result_code,
            'diagnostic': self.diagnostic,
            'owner': self.owner,
            'feedback_valid': self.feedback_valid,
            'pose_valid': self.pose_valid,
            'feedback_detail': getattr(self, 'feedback_detail', {}),
            'navigation_paused': bool(
                self.navigation_paused
                and not self.cancel_requested
                and self.state in ('awaiting_acceptance', 'accepted', 'executing')
            ),
            'pause_reason': self.pause_reason,
            'navigation_ready': bool(
                self.backend_ready()
                and self.feedback_valid
                and self.pose_valid
                and self.owner is None
                and self.manual_released
                and self.measured_stopped
                and not self.unknown_backend_activity()
            ),
            'manual_allowed': bool(self.manual_allowed()),
            'manual_released': self.manual_released,
            'cancel_requested': self.cancel_requested,
            'cancel_reason': self.cancel_reason,
            'backend_ready': bool(self.backend_ready()),
            'measured_stopped': bool(self.measured_stopped),
            'map_frame': self.settings['map_frame'],
            'base_frame': self.settings['base_frame'],
            'navigation_enabled': self.enabled,
        }
        message = String()
        message.data = json.dumps(payload, allow_nan=False, separators=(',', ':'))
        self.status_publisher.publish(message)
        self.last_status = time.monotonic()

    def pause_navigation(self, reason):
        # Retain ownership, request ID and backend handle. Never resubmit a goal.
        self.invalidate_commands()
        self.navigation_paused = True
        self.pause_reason = reason
        self.recovery_started = None
        self.diagnostic = 'Navigation paused; output zero: ' + reason

    def recover_navigation(self, now):
        # Every failed freshness/stop check restarts the continuous recovery window.
        # A terminal/uncertain/canceled action is never recreated here.
        self.invalidate_commands()
        if (
            self.cancel_requested
            or self.backend_handle is None
            or self.state not in ('accepted', 'executing')
            or not self.measured_stopped
        ):
            self.recovery_started = None
            return
        if self.recovery_started is None:
            self.recovery_started = now
        self.diagnostic = 'Navigation paused; waiting for 0.5 s of fresh feedback and measured stop'
        if now - self.recovery_started >= 0.5:
            self.navigation_paused = False
            self.pause_reason = None
            self.recovery_started = None
            self.nav_epoch = now
            self.diagnostic = (
                'Feedback recovered; continuing the same active goal with new velocity commands'
            )

    def tick(self):
        now = time.monotonic()
        self.refresh_feedback()
        unknown = self.unknown_backend_activity()
        if self.clock_reset or unknown:
            self.invalidate_commands()
            reason = (
                'Simulation clock reset; restart navigation and initialize localization'
                if self.clock_reset
                else 'Unexpected backend action activity'
            )
            if self.owner is not None and not self.cancel_requested:
                self.request_cancel(reason)
            self.diagnostic = reason + '; output inhibited'
        elif not self.feedback_valid or (self.owner is not None and not self.pose_valid):
            self.invalidate_commands()
            reason = (
                'Measured feedback invalid or stale'
                if not self.feedback_valid
                else 'Map localization TF unavailable or stale'
            )
            if self.owner is not None and not self.cancel_requested:
                self.pause_navigation(reason)
            else:
                self.diagnostic = reason + '; output zero'
        elif self.owner is not None:
            if self.navigation_paused:
                self.recover_navigation(now)
            elif (
                self.backend_handle is not None
                and not self.cancel_requested
                and self.state in ('accepted', 'executing')
                and self.nav_received > self.nav_epoch
                and now - self.nav_received <= self.settings['nav_timeout']
            ):
                self.command_publisher.publish(self.nav_command)
            else:
                self.zero()
        elif (
            not self.manual_released
            and now - self.manual_received <= self.settings['manual_timeout']
        ):
            self.command_publisher.publish(self.manual_command)
        else:
            if moving(self.manual_command):
                self.manual_command = Twist()
                self.manual_received = -math.inf
                self.diagnostic = (
                    'Manual watchdog expired; explicit zero release required before navigation'
                )
            elif self.feedback_valid and self.pose_valid:
                self.diagnostic = 'Ready: measured feedback and localization valid'
            self.zero()
        if now - self.last_status >= 0.2:
            self.publish_status()

    def stop(self):
        if self.closed:
            return
        self.closed = True
        self.timer.cancel()
        self.invalidate_commands()
        if self.owner is not None:
            self.request_cancel('Adapter shutdown')
        self.zero()
        self.diagnostic = 'Adapter shutting down; zero requested'
        self.publish_status()


def main(args=None):
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)

    def request_stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    node = None
    executor = SingleThreadedExecutor()
    try:
        node = WebAdapter()
        executor.add_node(node)
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            if rclpy.ok():
                node.stop()
                executor.spin_once(timeout_sec=0.05)
            executor.remove_node(node)
            node.action_server.destroy()
            node.backend.destroy()
            node.destroy_node()
        executor.shutdown()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
