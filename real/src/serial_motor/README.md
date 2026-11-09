# serial_motor

ROS 2 Humble motor commands, encoder feedback, and wheel odometry for FastBot on
Raspberry Pi 4 / Ubuntu 22.04 ARM64.

## Responsibilities and interfaces

| Interface | Type | Meaning |
| --- | --- | --- |
| `/fastbot/cmd_vel` | `geometry_msgs/msg/Twist` | Forward `linear.x` in m/s and yaw `angular.z` in rad/s |
| `/fastbot/encoder_vals` | `serial_motor_msgs/msg/EncoderVals` | Cumulative signed int32 wheel counts |
| `/fastbot/motor_vels` | `serial_motor_msgs/msg/MotorVels` | Measured wheel angular velocities in rad/s |
| `/fastbot/odom` | `nav_msgs/msg/Odometry` | Wheel-based planar pose and body velocity |
| `/fastbot/joint_states` | `sensor_msgs/msg/JointState` | Wheel joint positions and velocities |

The node converts valid velocity requests into proportionally limited integer `m`
commands. Serial writes must complete and receive `OK`; periodic `e` queries read
encoder feedback. Firmware handles controller-side speed regulation. This package
does not replace that firmware, and `serial_motor_msgs` does not operate hardware.

## Running and safety boundaries

The executable is `ros2 run serial_motor motor_driver`. Prefer the configured
bringup entry in the [root README](../README.md). A directly started node requires
positive finite wheel radius, separation, CPR, and controller rate; zero defaults
intentionally reject unconfigured operation.

The node's `serial_enabled` default is false. Real mode also requires a resolved
serial port, matching baud rate, and finite read/write timeouts. After a startup
wait, a `b` query checks controller readiness. The top-level bringup explicitly
enables real hardware by default. The initial 50-count target limit is not a
calibrated safe ground speed; reviewed pulse checks used a lower limit.

After the command timeout (normally 0.5 s), the node attempts a zero target.
Communication faults inhibit subsequent motion commands and clear command timing;
they do not prove a physical stop or automatically retry unconfirmed commands.
The main routine closes resources, including injected test connections.

The first encoder sample establishes a count/time baseline. Later samples use
actual monotonic intervals and advance the baseline only after valid calculations.
Wrap handling assumes true changes below `2**31` counts per sample and does not
detect controller reboot. Measured wheel feedback feeds Odometry, TF, and JointState.

## Engineering references

- [Flow](docs/flow.md), [tooling](docs/tooling.md), and [style profile](docs/style_profile.md)
- [Comment conventions](docs/comment_checks.md) and [tests](test/README.md)
- [Template provenance](docs/TEMPLATE_SOURCES.md)
- [Integration, frames, assumptions, and evidence](../docs/INTEGRATION.md)

Detailed learner attempts remain in the authoritative training records rather
than this public repository. Doxygen configuration is supplied; generated HTML
and debugger/UI tool acceptance are not implied by configuration-file presence.
