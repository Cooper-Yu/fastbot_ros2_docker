"""ROS 2 serial motor control and measured wheel feedback."""

import math
import time

import rclpy
import serial
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import JointState
from serial_motor_msgs.msg import EncoderVals, MotorVels
from serial_motor.device_paths import MOTOR_USB_IDS, resolve_serial_device
from tf2_ros import TransformBroadcaster


def compute_wheel_linear_speeds(linear_speed, angular_speed, wheel_separation):
    """
    @brief Convert requested robot motion to left and right wheel linear speeds.

    @param[in] linear_speed Requested forward speed in m/s from cmd_vel_callback.
    @param[in] angular_speed Requested yaw rate in rad/s from cmd_vel_callback.
    @param[in] wheel_separation Distance between wheel centerlines in meters.
    @return Left and right wheel speeds in m/s, retaining direction.
    @note The caller validates finite inputs and positive geometry.
    """
    left_speed = linear_speed - angular_speed * wheel_separation / 2
    right_speed = linear_speed + angular_speed * wheel_separation / 2
    return left_speed, right_speed


def compute_wheel_angular_speeds(left_linear_speed, right_linear_speed, wheel_radius):
    """
    @brief Convert wheel linear speeds to angular speeds.

    @param[in] left_linear_speed Left target speed in m/s from cmd_vel_callback.
    @param[in] right_linear_speed Right target speed in m/s from cmd_vel_callback.
    @param[in] wheel_radius Common wheel radius in meters; must be positive.
    @return Left and right target angular speeds in rad/s.
    @note No controller command is sent by this calculation.
    """
    if wheel_radius <= 0:
        raise ValueError('wheel_radius must be greater than zero')

    left_angular_speed = left_linear_speed / wheel_radius
    right_angular_speed = right_linear_speed / wheel_radius
    return left_angular_speed, right_angular_speed


def compute_encoder_counts_per_loop(
    left_angular_speed, right_angular_speed, encoder_cpr, loop_rate
):
    """
    @brief Convert wheel angular targets to counts per controller update.

    @param[in] left_angular_speed Left target in rad/s from cmd_vel_callback.
    @param[in] right_angular_speed Right target in rad/s from cmd_vel_callback.
    @param[in] encoder_cpr Encoder counts per wheel revolution; positive.
    @param[in] loop_rate Controller update frequency in Hz; positive.
    @return Signed fractional counts per update for the two wheels.
    @note Integer conversion is deferred until command formatting.
    """
    left_counts = left_angular_speed / (2 * math.pi) * encoder_cpr / loop_rate
    right_counts = right_angular_speed / (2 * math.pi) * encoder_cpr / loop_rate
    return left_counts, right_counts


def require_positive_finite(name, value):
    """
    @brief Reject a configuration value unless it is positive and finite.

    @param[in] name Parameter label used in the error message.
    @param[in] value Numeric configuration value supplied by the caller.
    @return The validated value unchanged.
    @note Invalid values raise ValueError before dependent calculations.
    """
    if value <= 0:
        raise ValueError(f'{name} must be greater than zero')
    if not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    return value


def compute_encoder_count_delta(current_count, previous_count):
    """
    @brief Calculate the shortest signed difference between int32 counts.

    @param[in] current_count Current cumulative count from a successful sample.
    @param[in] previous_count Previous cumulative count retained by the sampler.
    @return Signed count difference with one int32 wraparound corrected.
    @note Actual travel between samples must be less than 2**31 counts.
    Exactly half the range is ambiguous; controller resets are not detected.
    """
    for value in (current_count, previous_count):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError('Encoder counts must be integers')
        if not -2147483648 <= value <= 2147483647:
            raise ValueError('Encoder counts must fit int32')
    delta = current_count - previous_count
    if abs(delta) == 2**31:
        raise ValueError('Half-range encoder difference has ambiguous direction')
    if delta > 2147483647:
        delta = delta - 2**32
    elif delta < -2147483648:
        delta = delta + 2**32
    return delta


def compute_encoder_angular_speed(count_delta, elapsed, encoder_cpr):
    """
    @brief Calculate average measured angular speed over a sampling interval.

    @param[in] count_delta Signed count difference from the sampler.
    @param[in] elapsed Actual sampling interval in seconds; positive and finite.
    @param[in] encoder_cpr Counts per wheel revolution; positive and finite.
    @return Average wheel angular speed in rad/s.
    @note Wraparound is resolved before this conversion.
    """
    require_positive_finite('elapsed', elapsed)
    require_positive_finite('encoder_cpr', encoder_cpr)
    if not math.isfinite(count_delta):
        raise ValueError('count_delta must be finite')
    # Preserve signed motion; the sampler handles count wraparound.
    return ((count_delta / elapsed) / encoder_cpr) * (2 * math.pi)


def compute_robot_linear_speed(left_angular_speed, right_angular_speed, wheel_radius):
    """
    @brief Estimate robot forward speed from the measured wheel angular speeds.

    @param[in] left_angular_speed Measured left wheel angular speed in rad/s.
    @param[in] right_angular_speed Measured right wheel angular speed in rad/s.
    @param[in] wheel_radius Common wheel radius in meters; positive and finite.
    @return Estimated robot forward speed in m/s, retaining its sign.
    @note Used with measured wheel feedback, not requested motion.
    """
    require_positive_finite('wheel_radius', wheel_radius)
    if not all(math.isfinite(value) for value in (left_angular_speed, right_angular_speed)):
        raise ValueError('Wheel angular speeds must be finite')
    return (left_angular_speed + right_angular_speed) * wheel_radius / 2


def compute_robot_angular_speed(
    left_angular_speed, right_angular_speed, wheel_radius, wheel_separation
):
    """
    @brief Estimate robot yaw rate from the measured wheel angular speeds.

    @param[in] left_angular_speed Measured left wheel angular speed in rad/s.
    @param[in] right_angular_speed Measured right wheel angular speed in rad/s.
    @param[in] wheel_radius Common wheel radius in meters; positive and finite.
    @param[in] wheel_separation Wheel centerline distance in meters; positive and finite.
    @return Estimated robot yaw rate in rad/s; a left turn is positive.
    @note Used with measured wheel feedback, not requested motion.
    """
    require_positive_finite('wheel_radius', wheel_radius)
    require_positive_finite('wheel_separation', wheel_separation)
    if not all(math.isfinite(value) for value in (left_angular_speed, right_angular_speed)):
        raise ValueError('Wheel angular speeds must be finite')
    return (right_angular_speed - left_angular_speed) * wheel_radius / wheel_separation


def compute_motion_increments(linear_speed, angular_speed, elapsed):
    """
    @brief Calculate signed motion increments over one measured sample interval.

    @param[in] linear_speed Measured robot forward speed in m/s.
    @param[in] angular_speed Measured robot yaw rate in rad/s.
    @param[in] elapsed Actual sampling interval in seconds; positive and finite.
    @return Forward distance in meters and heading change in radians.
    @note These are interval increments, not absolute position.
    The sampler supplies its actual measured interval.
    """
    require_positive_finite('elapsed', elapsed)
    if not all(math.isfinite(value) for value in (linear_speed, angular_speed)):
        raise ValueError('Robot speeds must be finite')
    return linear_speed * elapsed, angular_speed * elapsed


def advance_planar_pose(x, y, heading, distance, heading_change):
    """
    @brief Advance a planar pose using the starting-heading approximation.

    @param[in] x Previous fixed-frame x position in meters.
    @param[in] y Previous fixed-frame y position in meters.
    @param[in] heading Previous heading in radians; left turns are positive.
    @param[in] distance Signed forward travel over this sample in meters.
    @param[in] heading_change Signed heading change over this sample in radians.
    @return Updated fixed-frame x, y in meters and heading in radians.
    @note Use the interval's starting heading for this approximate position step.
    Heading is not normalized here.
    """
    if not all(math.isfinite(value) for value in (x, y, heading, distance, heading_change)):
        raise ValueError('Pose and motion increments must be finite')
    return (
        x + distance * math.cos(heading),
        y + distance * math.sin(heading),
        heading + heading_change,
    )


def format_motor_command(left_counts, right_counts):
    """
    @brief Encode two target counts as a controller speed command.

    @param[in] left_counts Signed left target counts per controller update.
    @param[in] right_counts Signed right target counts per controller update.
    @return The m command string with integer targets and a final carriage return.
    @note int() truncates toward zero; this function performs no serial I/O.
    """
    return f'm {int(left_counts)} {int(right_counts)}\r'


def has_command_timed_out(elapsed, timeout):
    """
    @brief Check whether the last valid command has reached its deadline.

    @param[in] elapsed Seconds since the last accepted command.
    @param[in] timeout Command lifetime in seconds.
    @return True at or beyond the deadline; otherwise False.
    @note The caller supplies valid time values.
    """
    return elapsed >= timeout


def send_motor_command(connection, command):
    """
    @brief Write one complete UTF-8 command and require an OK response.

    @param[in,out] connection Finite-timeout serial transport or protocol double.
    @param[in] command Command string created by format_motor_command.
    @return The number of bytes written after acknowledgment succeeds.
    @note Partial writes and invalid responses raise without automatic retries.
    An acknowledgment confirms protocol handling, not physical motion accuracy.
    """
    payload = command.encode('utf-8')
    written = connection.write(payload)
    if written != len(payload):
        raise OSError('Incomplete motor command write')
    # Real serial connections must use a finite read timeout.
    response = connection.readline().decode('utf-8').strip()
    if response != 'OK':
        raise RuntimeError('Motor command not acknowledged: ' + repr(response))
    return written


def prepare_serial_connection(connection_factory, port, baud_rate, read_timeout, write_timeout):
    """
    @brief Configure a closed serial connection with finite timeouts.

    @param[in] connection_factory Serial constructor supplied by main or a test.
    @param[in] port Device path assigned to the initially closed connection.
    @param[in] baud_rate Configured serial baud rate.
    @param[in] read_timeout Positive finite read timeout in seconds.
    @param[in] write_timeout Positive finite write timeout in seconds.
    @return The configured connection, still closed.
    @note Opening and final ownership are handled by the caller.
    """
    require_positive_finite('read_timeout', read_timeout)
    require_positive_finite('write_timeout', write_timeout)
    connection = connection_factory(
        port=None,
        baudrate=baud_rate,
        timeout=read_timeout,
        write_timeout=write_timeout,
    )
    connection.port = port
    return connection


def open_prepared_connection(connection):
    """
    @brief Open a configured connection and clean up a failed open.

    @param[in,out] connection Closed transport returned by preparation.
    @return The same connection after a successful open.
    @note An opening exception is propagated after attempting close.
    """
    try:
        connection.open()
    except Exception:
        connection.close()
        raise
    return connection


def check_controller_ready(connection, expected_baud, wait_seconds=2.5):
    """
    @brief Wait for startup and validate the controller baud query.

    @param[in,out] connection Open transport owned by main.
    @param[in] expected_baud Baud rate configured for the controller.
    @param[in] wait_seconds Positive finite startup delay in seconds.
    @return The baud rate reported by the controller.
    @note Startup input is discarded before the read-only b query.
    """
    require_positive_finite('startup_wait', wait_seconds)
    time.sleep(wait_seconds)
    connection.reset_input_buffer()
    payload = b'b\r'
    if connection.write(payload) != len(payload):
        raise OSError('Incomplete startup query write')
    response = connection.readline().decode('utf-8').strip()
    reported_baud = int(response)
    if reported_baud != expected_baud:
        raise RuntimeError('Controller baud rate mismatch')
    return reported_baud


def limit_motor_counts(left_counts, right_counts, max_counts):
    """
    @brief Limit both wheel targets by one common scale factor.

    @param[in] left_counts Signed left target counts per update.
    @param[in] right_counts Signed right target counts per update.
    @param[in] max_counts Positive absolute limit, at most 32767.
    @return Limited left and right targets, preserving their ratio and signs.
    @note The integer range limit is not a calibrated physical safety limit.
    """
    require_positive_finite('max_counts', max_counts)
    if max_counts > 32767:
        raise ValueError('max_counts exceeds the controller integer range')
    if not all(math.isfinite(value) for value in (left_counts, right_counts)):
        raise ValueError('motor targets must be finite')
    peak = max(abs(left_counts), abs(right_counts))
    if peak <= max_counts:
        return left_counts, right_counts
    scale = max_counts / peak
    return left_counts * scale, right_counts * scale


def read_encoder_values(connection):
    """
    @brief Query one complete encoder response and validate its two counts.

    @param[in,out] connection Open transport with finite read and write timeouts.
    @return Left and right cumulative counts within the int32 message range.
    @note Short writes, partial lines and invalid fields raise an exception.
    """
    payload = b'e\r'
    if connection.write(payload) != len(payload):
        raise OSError('Incomplete encoder query write')
    response = connection.readline()
    if not response.endswith(b'\n'):
        raise RuntimeError('Incomplete encoder response')
    fields = response.decode('utf-8').strip().split()
    if len(fields) != 2:
        raise RuntimeError('Expected two encoder values')
    left_encoder = int(fields[0])
    right_encoder = int(fields[1])
    if not all(-2147483648 <= value <= 2147483647 for value in (left_encoder, right_encoder)):
        raise ValueError('Encoder value outside int32 range')
    return left_encoder, right_encoder


class MotorDriver(Node):
    """@brief Handle ROS motion requests, serial commands and encoder feedback."""

    def __init__(self, connection=None):
        """
        @brief Configure preview mode, parameters, subscriptions and feedback timers.

        @param[in,out] connection Optional transport injected by main or a test.
        @note No serial device is opened by this constructor. Preview is the default.
        """
        super().__init__('motor_driver', namespace='fastbot')
        try:
            self.connection = connection
            self.communication_fault = False
            self.x = 0.0
            self.y = 0.0
            self.heading = 0.0
            self.wheel_positions = (0.0, 0.0)
            self.body_velocity = (0.0, 0.0)
            self.previous_encoder_sample = None
            self.serial_enabled = self.declare_parameter('serial_enabled', False).value
            self.serial_port = self.declare_parameter('serial_port', '').value
            self.baud_rate = self.declare_parameter('baud_rate', 57600).value
            self.serial_read_timeout = self.declare_parameter('serial_read_timeout', 0.2).value
            self.serial_write_timeout = self.declare_parameter('serial_write_timeout', 0.2).value
            require_positive_finite('baud_rate', self.baud_rate)
            # Zero defaults require explicit geometry and controller parameters.
            self.declare_parameter('wheel_separation', 0.0)
            self.declare_parameter('wheel_radius', 0.0)
            self.declare_parameter('encoder_cpr', 0)
            self.declare_parameter('loop_rate', 0)

            self.wheel_separation = self.get_parameter('wheel_separation').value
            self.wheel_radius = self.get_parameter('wheel_radius').value
            self.encoder_cpr = self.get_parameter('encoder_cpr').value
            self.loop_rate = self.get_parameter('loop_rate').value

            require_positive_finite('wheel_separation', self.wheel_separation)
            require_positive_finite('wheel_radius', self.wheel_radius)
            require_positive_finite('encoder_cpr', self.encoder_cpr)
            require_positive_finite('loop_rate', self.loop_rate)
            self.max_counts_per_loop = self.declare_parameter('max_counts_per_loop', 50.0).value
            require_positive_finite('max_counts_per_loop', self.max_counts_per_loop)
            if self.max_counts_per_loop > 32767:
                raise ValueError('max_counts_per_loop exceeds the controller integer range')

            self.command_timeout = self.declare_parameter('command_timeout', 0.5).value
            require_positive_finite('command_timeout', self.command_timeout)
            self.last_command_time = None

            self.cmd_vel_subscription = self.create_subscription(
                Twist, 'cmd_vel', self.cmd_vel_callback, 10
            )
            self.timeout_timer = self.create_timer(0.05, self.check_command_timeout)
            self.encoder_pub_ = self.create_publisher(EncoderVals, 'encoder_vals', 10)
            self.motor_vel_pub_ = self.create_publisher(MotorVels, 'motor_vels', 10)
            self.configure_odometry()
            self.encoder_timer = self.create_timer(0.1, self.publish_encoder_values)
        except Exception:
            self.destroy_node()
            raise

    def configure_odometry(self):
        """@brief Configure body-frame output publishers without opening hardware."""
        self.odom_frame = self.declare_parameter('odom_frame', 'fastbot_odom').value
        self.base_frame = self.declare_parameter('base_frame', 'fastbot_base_link').value
        self.publish_tf = self.declare_parameter('publish_tf', True).value
        self.joint_prefix = self.declare_parameter('joint_prefix', 'fastbot_').value
        if not self.odom_frame or not self.base_frame or self.odom_frame == self.base_frame:
            raise ValueError('Odometry and base frame names must be nonempty and distinct')
        self.odom_pub_ = self.create_publisher(Odometry, 'odom', 10)
        self.joint_pub_ = self.create_publisher(JointState, 'joint_states', 10)
        self.tf_broadcaster = TransformBroadcaster(self) if self.publish_tf else None

    def cmd_vel_callback(self, msg):
        """
        @brief Convert a valid velocity request into limited controller targets.

        @param[in] msg Twist containing forward linear.x and yaw angular.z.
        @note Only accepted commands refresh the command deadline.
        A latched communication fault rejects further motion inputs.
        """
        if self.communication_fault:
            self.get_logger().error('Motion input rejected after communication fault')
            return
        linear_speed = msg.linear.x
        angular_speed = msg.angular.z
        self.get_logger().info(
            f'Received linear.x={linear_speed} m/s; angular.z={angular_speed} rad/s'
        )

        # Reuse the finite-value rule; signed or zero motion inputs remain valid.
        if not math.isfinite(linear_speed) or not math.isfinite(angular_speed):
            self.get_logger().error('Rejected non-finite motion input')
            return

        left_linear_speed, right_linear_speed = compute_wheel_linear_speeds(
            linear_speed, angular_speed, self.wheel_separation
        )
        left_angular_speed, right_angular_speed = compute_wheel_angular_speeds(
            left_linear_speed, right_linear_speed, self.wheel_radius
        )
        left_counts, right_counts = compute_encoder_counts_per_loop(
            left_angular_speed, right_angular_speed, self.encoder_cpr, self.loop_rate
        )

        if not all(math.isfinite(value) for value in (left_counts, right_counts)):
            self.get_logger().error('Rejected non-finite calculation result')
            return
        left_counts, right_counts = limit_motor_counts(
            left_counts, right_counts, self.max_counts_per_loop
        )
        self.get_logger().info(f'Target counts/update: left={left_counts}; right={right_counts}')

        command = format_motor_command(left_counts, right_counts)
        self.get_logger().info('Motor command preview: ' + repr(command))
        if not self.send_command_safely(command):
            return
        self.last_command_time = time.monotonic()

    def send_command_safely(self, command):
        """
        @brief Send an acknowledged command or latch a communication fault.

        @param[in] command Formatted command from the callback or stop path.
        @return True for preview or an acknowledged send; False on a fault.
        @note Faults inhibit further sends and clear the command timestamp.
        No retry or physical stopping confirmation is implied by the fault flag.
        """
        if self.communication_fault:
            return False
        if self.connection is None:
            return True
        try:
            send_motor_command(self.connection, command)
        except (OSError, RuntimeError, UnicodeError) as error:
            self.communication_fault = True
            self.last_command_time = None
            self.get_logger().error('Motor communication failed; unconfirmed: ' + str(error))
            return False
        return True

    def update_encoder_speed_sample(self, left_encoder, right_encoder, sample_time):
        """
        @brief Derive wheel angular speeds from consecutive successful samples.

        @param[in] left_encoder Current left cumulative int32 count.
        @param[in] right_encoder Current right cumulative int32 count.
        @param[in] sample_time Host monotonic time after reading the response.
        @return None for the first sample; otherwise left and right rad/s.
        @note The baseline advances only after both wheel calculations succeed.
        """
        current_sample = (left_encoder, right_encoder, sample_time)
        if self.previous_encoder_sample is None:
            self.previous_encoder_sample = current_sample
            return None
        previous_left, previous_right, previous_time = self.previous_encoder_sample
        # Use the actual interval between successful encoder samples.
        left_delta = compute_encoder_count_delta(current_sample[0], previous_left)
        right_delta = compute_encoder_count_delta(current_sample[1], previous_right)
        elapsed = current_sample[2] - previous_time
        require_positive_finite('elapsed', elapsed)
        # Advance the baseline only after both calculations succeed.
        left_angular_speed = compute_encoder_angular_speed(left_delta, elapsed, self.encoder_cpr)
        right_angular_speed = compute_encoder_angular_speed(right_delta, elapsed, self.encoder_cpr)
        self.update_pose(left_angular_speed, right_angular_speed, elapsed)
        self.previous_encoder_sample = current_sample
        return left_angular_speed, right_angular_speed

    def update_pose(self, left_speed, right_speed, elapsed):
        """
        @brief Commit one complete measured interval to body and wheel state.

        @param[in] left_speed Measured left wheel angular speed in rad/s.
        @param[in] right_speed Measured right wheel angular speed in rad/s.
        @param[in] elapsed Actual monotonic interval in seconds.
        @note All candidate values are validated before any state is committed.
        """
        linear = compute_robot_linear_speed(left_speed, right_speed, self.wheel_radius)
        angular = compute_robot_angular_speed(
            left_speed, right_speed, self.wheel_radius, self.wheel_separation
        )
        distance, change = compute_motion_increments(linear, angular, elapsed)
        pose = advance_planar_pose(self.x, self.y, self.heading, distance, change)
        wheels = (
            self.wheel_positions[0] + left_speed * elapsed,
            self.wheel_positions[1] + right_speed * elapsed,
        )
        if not all(math.isfinite(value) for value in (*pose, *wheels, linear, angular)):
            raise ValueError('Non-finite accumulated odometry')
        self.x, self.y, self.heading = pose
        self.wheel_positions = wheels
        self.body_velocity = (linear, angular)

    def publish_odometry(self, angular_speeds):
        """
        @brief Publish accumulated pose, measured body velocity, TF and wheel joints.

        @param[in] angular_speeds Left/right measured angular speeds in rad/s.
        @note Uses ROS timestamps for messages and monotonic intervals for integration.
        Covariances are initial estimates, not a calibrated accuracy claim.
        """
        stamp = self.get_clock().now().to_msg()
        message = Odometry()
        message.header.stamp = stamp
        message.header.frame_id = self.odom_frame
        message.child_frame_id = self.base_frame
        message.pose.pose.position.x = self.x
        message.pose.pose.position.y = self.y
        message.pose.pose.orientation.z = math.sin(self.heading / 2)
        message.pose.pose.orientation.w = math.cos(self.heading / 2)
        message.twist.twist.linear.x = self.body_velocity[0]
        message.twist.twist.angular.z = self.body_velocity[1]
        for index, variance in ((0, 0.05), (7, 0.05), (14, 1e6), (21, 1e6), (28, 1e6), (35, 0.1)):
            message.pose.covariance[index] = variance
            message.twist.covariance[index] = variance
        self.odom_pub_.publish(message)
        if self.tf_broadcaster is not None:
            transform = TransformStamped()
            transform.header = message.header
            transform.child_frame_id = self.base_frame
            transform.transform.translation.x = self.x
            transform.transform.translation.y = self.y
            transform.transform.rotation = message.pose.pose.orientation
            self.tf_broadcaster.sendTransform(transform)
        joints = JointState()
        joints.header.stamp = stamp
        joints.name = [
            self.joint_prefix + 'left_wheel_joint',
            self.joint_prefix + 'right_wheel_joint',
        ]
        joints.position = list(self.wheel_positions)
        joints.velocity = list(angular_speeds)
        self.joint_pub_.publish(joints)

    def publish_encoder_values(self):
        """
        @brief Query cumulative counts and publish measured wheel feedback.

        @note Serial transactions share the default mutually exclusive callback group.
        The first valid sample publishes counts but does not guess a wheel speed.
        Read or calculation failures latch a fault and inhibit later communication.
        """
        if self.connection is None or self.communication_fault:
            return
        try:
            left_encoder, right_encoder = read_encoder_values(self.connection)
            sample_time = time.monotonic()
        except (OSError, RuntimeError, ValueError) as error:
            self.communication_fault = True
            self.last_command_time = None
            self.get_logger().error('Encoder read failed; result unconfirmed: ' + str(error))
            return
        message = EncoderVals()
        message.mot_1_enc_val = left_encoder
        message.mot_2_enc_val = right_encoder
        self.encoder_pub_.publish(message)
        try:
            angular_speeds = self.update_encoder_speed_sample(
                left_encoder, right_encoder, sample_time
            )
        except (ValueError, OverflowError) as error:
            self.communication_fault = True
            self.last_command_time = None
            self.get_logger().error('Encoder speed calculation failed: ' + str(error))
            return
        if angular_speeds is None:
            return
        self.get_logger().info(f'Encoder angular speeds (rad/s): {angular_speeds!r}')
        velocity_message = MotorVels()
        velocity_message.mot_1_rad_sec = angular_speeds[0]
        velocity_message.mot_2_rad_sec = angular_speeds[1]
        self.motor_vel_pub_.publish(velocity_message)
        self.publish_odometry(angular_speeds)

    def check_command_timeout(self):
        """
        @brief Attempt a zero target after the valid command lifetime expires.

        @note The timestamp is cleared after preview or an acknowledged zero.
        A failed send latches a fault without claiming a confirmed physical stop.
        """
        if self.last_command_time is None:
            return
        elapsed = time.monotonic() - self.last_command_time
        if not has_command_timed_out(elapsed, self.command_timeout):
            return
        command = format_motor_command(0, 0)
        self.get_logger().info('Timeout stop preview: ' + repr(command))
        if not self.send_command_safely(command):
            return
        self.last_command_time = None


def main(args=None, connection=None):
    """
    @brief Own ROS and serial resources through startup, execution and cleanup.

    @param[in] args Optional ROS command-line arguments.
    @param[in,out] connection Optional injected transport; closed during cleanup.
    @note Hardware is enabled only by an explicit serial_enabled parameter.
    Cleanup attempts zero unless a communication fault is already latched.
    """
    node = None
    initialized = False
    try:
        rclpy.init(args=args)
        initialized = True
        node = MotorDriver(connection=connection)
        if node.serial_enabled and connection is None:
            node.serial_port = resolve_serial_device(
                node.serial_port, 'arduino_nano', MOTOR_USB_IDS
            )
            connection = prepare_serial_connection(
                serial.Serial,
                node.serial_port,
                node.baud_rate,
                node.serial_read_timeout,
                node.serial_write_timeout,
            )
            open_prepared_connection(connection)
            check_controller_ready(connection, node.baud_rate)
            node.connection = connection
            node.get_logger().info(f'Serial controller ready on {node.serial_port}; limits active')
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if node is not None:
                try:
                    if connection is not None and not node.communication_fault:
                        node.send_command_safely(format_motor_command(0, 0))
                finally:
                    node.destroy_node()
        finally:
            try:
                if connection is not None:
                    connection.close()
            finally:
                if initialized and rclpy.ok():
                    rclpy.shutdown()


if __name__ == '__main__':
    main()
