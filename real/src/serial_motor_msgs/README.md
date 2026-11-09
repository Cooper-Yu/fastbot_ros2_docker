# serial_motor_msgs

ROS 2 message interfaces generated with `ament_cmake` and `rosidl`. This package
does not run motors or own a serial connection.

| Message | Fields | Units and purpose |
| --- | --- | --- |
| `EncoderVals` | `int32 mot_1_enc_val`, `int32 mot_2_enc_val` | Cumulative left/right encoder counts |
| `MotorVels` | `float32 mot_1_rad_sec`, `float32 mot_2_rad_sec` | Left/right wheel angular velocities in rad/s |
| `MotorCommands` | `bool is_pwm`, `float32 mot_1_req_rad_sec`, `float32 mot_2_req_rad_sec` | Command interface definition; the current driver receives Twist |

The interfaces were built and displayed on the target Pi/Humble environment and
imported from Python. Actual EncoderVals/MotorVels publication was checked with
the driver. Interface installation alone does not imply a running node.

## Build and inspect

```bash
cd ~/ros2_ws
colcon build --packages-select serial_motor_msgs
source install/setup.bash
ros2 interface show serial_motor_msgs/msg/EncoderVals
```

Definitions live in `msg/`. `CMakeLists.txt` registers all three interfaces;
`package.xml` declares generation/runtime dependencies and interface-package group
membership. Student-authored code is Apache-2.0; see the root LICENSE and NOTICE.

## Engineering references

- [Flow](docs/flow.md), [tooling](docs/tooling.md), and [style profile](docs/style_profile.md)
- [Comment conventions](docs/comment_checks.md), [tests](test/README.md), and
  [template provenance](docs/TEMPLATE_SOURCES.md)

Detailed learner answers and runtime evidence remain in the authoritative training
records. Supplied Doxygen configuration does not imply generated HTML acceptance.
