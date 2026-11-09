# serial_motor_msgs checks

The package retains its ament lint checks. Interface generation, display, and
Python import were verified separately after building; a lint result is not a
functional message-transport test.

```bash
cd ~/ros2_ws
colcon build --packages-select serial_motor_msgs
colcon test --packages-select serial_motor_msgs
colcon test-result --verbose
```

Actual EncoderVals/MotorVels transport is checked with the motor driver. A test
collector may report both a CTest wrapper and its underlying XML results; do not
count them as independent behavioral cases. See the
[integration guide](../../docs/INTEGRATION.md) for observed evidence and limits.
Detailed learner attempts remain in the authoritative training records.
