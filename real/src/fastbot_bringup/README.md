# fastbot_bringup

Coordinate the motor, robot-description, N10 lidar, and V4L2 camera drivers in ROS 2
Humble. This package owns launch wiring and configuration, not firmware control.

## Entry points

```bash
ros2 launch fastbot_bringup bringup.launch.xml
```

The default opens physical devices. For preview without hardware:

```bash
ros2 launch fastbot_bringup bringup.launch.xml \
  serial_enabled:=false lidar_enabled:=false camera_enabled:=false
```

Launch arguments include `robot_name`, `serial_enabled`, `serial_port`,
`lidar_enabled`, `lidar_port`, `camera_enabled`, and `camera_device`. Empty serial
paths select a unique known device or reject ambiguity. See the
[integration guide](../docs/INTEGRATION.md) for dependencies, topic names, measured
parameters, camera configuration, stop behavior, and verification limits.

The reviewed RViz configuration is `rviz/fastbot_sensors.rviz`. The `tools/`
directory contains software previews, camera-configuration checks, sensor checks,
and explicitly bounded motor/keyboard checks. Hardware checks require current
authorization and onsite setup; the existence of a tool is not permission to run it.

## Engineering references

| Reference | Purpose |
| --- | --- |
| [flow.md](docs/flow.md) | Data and control flow |
| [tooling.md](docs/tooling.md) | Tool entry points and checks |
| [style_profile.md](docs/style_profile.md) | Formatting and naming conventions |
| [test/README.md](test/README.md) | Actual tests and their boundaries |
| [api.dox](docs/api.dox) | Doxygen source entry |
| [engineering.canvas](docs/engineering.canvas) | Links between engineering files |
| [TEMPLATE_SOURCES.md](docs/TEMPLATE_SOURCES.md) | Template sources and licenses |

VS Code build/debug tasks are supplied. To generate documentation, when Doxygen
is installed, run `doxygen docs/Doxyfile` from this package. The pinned Doxygen
Awesome assets retain their licenses. Configuration presence does not certify
generated HTML, debugger UI behavior, official grading, or learner completion.
