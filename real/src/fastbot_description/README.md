# fastbot_description

A simplified FastBot URDF and robot_state_publisher launch configuration for ROS 2
Humble. The model includes wheel geometry and approximate sensor mounting frames.
It is not a manufacturer CAD model or a calibrated sensor-extrinsic description.

## Responsibilities and launch

The package provides fixed robot geometry and frame relationships. The motor
driver separately publishes measured wheel joint states and the odometry transform.

```bash
ros2 launch fastbot_description robot_state_publisher.launch.py
```

The full system is launched through `fastbot_bringup/bringup.launch.xml`; see the
[integration guide](../docs/INTEGRATION.md) for frame conventions and assumptions.
This description package does not open motors or sensor devices by itself.

## Verification and engineering references

URDF parsing and actual robot_state_publisher startup were checked in the preview
launch. The test directory does not contain a dedicated behavioral test suite.
Visualizing a simplified model does not verify physical dimensions or calibration.

- [Flow](docs/flow.md), [tooling](docs/tooling.md), and [style profile](docs/style_profile.md)
- [API documentation source](docs/api.dox), [test scope](test/README.md), and
  [template provenance](docs/TEMPLATE_SOURCES.md)

VS Code tasks and Doxygen configuration are provided as tooling support. When
Doxygen is installed, run `doxygen docs/Doxyfile` from this package. Generated
documentation and UI tooling remain separate from runtime/official acceptance.
