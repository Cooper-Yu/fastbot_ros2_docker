# FastBot Docker Project

Run FastBot simulation and real-robot SLAM in ROS 2 Humble / Ubuntu 22.04 containers.

## 1. Download the repository

Run on the simulation computer or, for Task 2, in an SSH terminal on the FastBot:

```bash
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
git clone https://github.com/Cooper-Yu/fastbot_ros2_docker.git
cd fastbot_ros2_docker
```

If the repository already exists, use that checkout and preserve its local `.env` files.
Docker and Docker Compose must be installed, the Docker daemon must be running, and
Docker commands must be available to the current user.

All application images are published in
[`cooper992/cooper12138-cp22`](https://hub.docker.com/r/cooper992/cooper12138-cp22).

| Task | Image tags | Platform |
| --- | --- | --- |
| Simulation | `fastbot-ros2-gazebo`, `fastbot-ros2-slam`, `fastbot-ros2-webapp` | `linux/amd64` |
| Real robot | `fastbot-ros2-real`, `fastbot-ros2-slam-real` | `linux/arm64` |

## 2. Task 1: Start the simulation

The following configuration targets The Construct rosject **1017054**, with X11
`DISPLAY=:1` and host UID/GID `1026:1026`. The containers run Humble independently
of the host ROS distribution. The full Gazebo GUI and camera profile uses a
**4-core CPU limit and 4 GiB memory limit**; the rosject must have enough resources.
For local WSL graphics, use [the local configuration](simulation/COMPOSE_LOCAL.md).

### First deployment only

From the repository root:

```bash
cd simulation
cp compose.cloud.yaml docker-compose.yml
```

Create `simulation/.env` if it does not already exist:

```dotenv
CP23_RUN_ID=cp23-cloud
CLOUD_UID=1026
CLOUD_GID=1026
DISPLAY=:1
```

Create `simulation/cloud_passwd` if it does not already exist:

```text
root:x:0:0:root:/root:/bin/bash
user:x:1026:1026:CP23:/tmp:/bin/bash
```

These are host-specific runtime files. Preserve existing files on a configured
rosject. The password-file mapping contains no passwords.

### Start and check

```bash
cd ~/ros2_ws/src/fastbot_ros2_docker/simulation
docker-compose up
```

Keep this terminal running. Pressing `Ctrl+C` stops the containers.
In another terminal:

```bash
docker ps
docker images
```

Expect three running services and the three simulation image tags listed above.
The cloud configuration pulls fixed image digests. If `docker images` shows
`<none>` tags after the pull, restore readable aliases for the same image contents:

```bash
cd ~/ros2_ws/src/fastbot_ros2_docker
python3 simulation/tag_published_images.py
```

Open **Graphical Tools** and check that Gazebo shows the room and FastBot.
Then obtain the web addresses:

```bash
webpage_address
rosbridge_address
```

Open the URL returned by `webpage_address`. Paste the address returned by
`rosbridge_address` into **ROSbridge session URL**, then click **Connect**.
When **Ready · hold to drive** appears, hold and drag the joystick to move;
release it to stop. Check that the page displays the live SLAM map.

## 3. Task 2: Start the real robot

From the computer's terminal, connect to the tested FastBot by SSH:

```bash
ssh yg-fastbot@yg-fastbot.local
```

Use your robot's SSH username and address if they differ. A prompt such as
`cooper@WIN-...` is the computer/WSL shell; the tested robot prompt is
`yg-fastbot@yg-fastbot`.

Run the following commands **on the ARM64 FastBot computer**, with its motor controller,
N10 LiDAR and camera connected. The tested profile uses Ubuntu 22.04, host UID/GID
`1000:1000`, and device groups `dialout=20` and `video=44`.

```bash
cd ~/ros2_ws/src/fastbot_ros2_docker/real
python3 prepare_env.py
```

Run preparation only when `real/.env` is absent. It discovers device paths and
creates the configuration without starting hardware. If `.env` already exists,
review and retain it. Check `MOTOR_DEVICE`, `LIDAR_DEVICE`, `CAMERA_DEVICE`,
`ROS_BASE`, `ROS_DOMAIN_ID`, and `CP23_RUN_ID` against this robot.

The robot uses Compose V2. If the guide's `docker-compose` spelling is missing,
install the repository's wrapper for the already installed Compose V2:

```bash
if ! command -v docker-compose >/dev/null 2>&1; then
  install -D -m 755 docker-compose "$HOME/.local/bin/docker-compose"
fi
export PATH="$HOME/.local/bin:$PATH"
sudo systemctl enable --now docker
docker-compose up
```

The two application services are `fastbot-ros2-real` and `fastbot-ros2-slam-real`.
Published images are used when available; source builds are documented in
[the real-robot guide](real/README.md).

In another robot terminal:

```bash
docker ps
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
unset CYCLONEDDS_URI
ros2 topic list --no-daemon
```

Check for `/fastbot/scan`, `/fastbot_camera/image_raw`, `/fastbot/cmd_vel`, and `/map`.

The Construct may set `CYCLONEDDS_URI` to a Husarnet-specific configuration.
The tested LAN/WSL connection uses the default Cyclone DDS interfaces instead;
`unset` changes only the current shell. If only `/parameter_events` and `/rosout`
appear, clear the ROS CLI daemon cache and check again:

```bash
ros2 daemon stop
ros2 topic list --no-daemon
```

### Power-on recovery

Both services use `restart: unless-stopped`. Leave them running and shut down the Pi:

```bash
sudo poweroff
```

After shutdown, disconnect and restore power. Reconnect from the computer:

```bash
ssh yg-fastbot@yg-fastbot.local
```

On the Pi, check automatic recovery **without running `docker-compose up` first**:

```bash
docker ps
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
unset CYCLONEDDS_URI
ros2 topic list --no-daemon
```

Both application containers and the sensor/map topics should be present.
Containers deliberately stopped with `Ctrl+C` must be started again before this test.

### External computer: WSL topics and RViz2

Use a **local WSL terminal, not an SSH shell on the Pi**. The tested bridge/viewer
must already be running; first-time setup is in
[the WSL connection guide](real/README.md#external-computer-and-wsl).

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=194 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
unset CYCLONEDDS_URI
ros2 topic list --no-daemon
rviz2 -d ~/ros2_ws/src/fastbot_ros2_docker/real/real_mapping.rviz
```

Expect the same robot topics, **Global Status: Ok**, and a live map with
**Fixed Frame = map**. If an RViz viewer is already open, inspect it rather than
starting another viewer. Pi domain 0 and WSL domain 194 are connected by the
project's optional network bridge; do not interchange these settings.

## Verification and references

- [Grading Guide audit](GRADING_GUIDE_AUDIT.md): observed results and environment adaptations.
- [Cloud runtime](cloud_runtime.lock.json) and [simulation image digests](hub_release.lock.json).
- [Real-robot image digests](real/release.lock.json) and [runtime evidence summary](real/runtime.lock.json).
- [Asset provenance](course_assets.lock.json); upstream license markings are retained.
- [Historical engineering notes in Chinese](docs/engineering_notes.zh.md).

Functional checks have been performed; official grading has not been submitted.
Keep `.env`, credentials, and `runtime_logs/` out of Git.
