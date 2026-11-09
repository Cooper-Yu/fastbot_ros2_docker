# Task 1: FastBot Simulation Containers

The three application images provide Gazebo simulation, Cartographer SLAM and
the web dashboard. See the [project README](../README.md#2-task-1-start-the-simulation)
for the complete cloud setup and Grading Guide command sequence.

| Service | Responsibility |
| --- | --- |
| `fastbot-ros2-gazebo` | Room, robot, physics, LiDAR, odometry, TF and camera |
| `fastbot-ros2-slam` | Live map generation from scan and odometry |
| `fastbot-ros2-webapp` | HTTP dashboard, ROSbridge and bounded manual control |

## The Construct

- Target rosject: **1017054**; application containers use ROS 2 Humble / Ubuntu 22.04.
- Deploy `compose.cloud.yaml` as `docker-compose.yml` in this directory.
- Host-specific files: `.env` and `cloud_passwd`; tested UID/GID `1026:1026`, `DISPLAY=:1`.
- Shared ROS domain: `193`; host HTTP port: `7000`; ROSbridge port: `9090`.
- Full Gazebo GUI/camera profile: **4 CPU cores and 4 GiB memory limit**.

From the configured cloud project:

```bash
cd ~/ros2_ws/src/fastbot_ros2_docker/simulation
docker-compose up
```

Keep this terminal running. In another terminal:

```bash
docker ps
docker images
webpage_address
rosbridge_address
```

Check the room and FastBot in **Graphical Tools**. Open the returned webpage URL,
connect using the returned ROSbridge address, and check joystick control and the
live map. Hold and drag the joystick to move; release to stop.

## Local WSL

See [COMPOSE_LOCAL.md](COMPOSE_LOCAL.md) for three-service live mapping and
[dashboard/README.md](dashboard/README.md) for the separate saved-map navigation profile.

## Timing and verification

A previous 2-core CPU limit throttled Gazebo enough for scan receipt intervals to
exceed the 0.5-second feedback limit. A 4-core limit reduced the observed maximum
interval to 0.377 seconds. Native joystick hold for four seconds, real motion and
release stop were verified with the original feedback/watchdog limits retained.

The latest cloud map is a new SLAM session and may contain unknown regions;
historical local whole-room map files remain separate. Runtime verification and
formal grading are separate records; official grading has not been submitted.

See [the audit](../GRADING_GUIDE_AUDIT.md), [cloud runtime](../cloud_runtime.lock.json),
[image digests](../hub_release.lock.json), and [asset provenance](../course_assets.lock.json).
