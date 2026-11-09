# serial_motor tests

The pytest suite checks motion calculations, protocol/fault behavior, odometry,
ROS feedback transport, and device-path selection. Native ament lint tests are
retained. No always-passing placeholder is used as behavioral evidence.

```bash
cd ~/ros2_ws
colcon test --packages-select serial_motor
colcon test-result --verbose
```

Run tests in the named Linux/Humble environment after building and sourcing the
workspace. Fake-connection tests do not certify physical wheel accuracy. Actual
ROS transport tests are distinct from publisher-recording substitutes; bounded
hardware checks and their authorizations are documented separately in
[the integration guide](../../docs/INTEGRATION.md).

Keep each case's input, initial state, expected behavior, tolerances, and boundary
reason explicit. Ruff and ament have different scopes; investigate conflicts
instead of globally disabling existing checks. Detailed learner attempts and
dated evidence remain in the authoritative training records.
