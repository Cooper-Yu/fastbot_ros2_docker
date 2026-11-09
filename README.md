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

## 3. Task 2: Real robot — Grading Guide

Use the FastBot's SSH terminal for steps 1–3. Docker, the device configuration and
images must already be prepared; see [first-time setup](real/SETUP.md) if needed.

### 1. Start the two containers

```bash
ssh yg-fastbot@yg-fastbot.local
cd ~/ros2_ws/src/fastbot_ros2_docker/real
docker-compose up
```

Keep this terminal running. In another SSH terminal:

```bash
docker ps
```

Expect `fastbot-ros2-real` and `fastbot-ros2-slam-real` to be running.

### 2. Check the robot topics

In the robot's SSH terminal:

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
unset CYCLONEDDS_URI
ros2 topic list --no-daemon
```

Check `/fastbot/scan` (LiDAR), `/fastbot_camera/image_raw` (camera),
`/fastbot/cmd_vel` (velocity command), and `/map`.

### 3. Check automatic startup after a power cycle

Leave the containers running, then shut down the Pi:

```bash
sudo poweroff
```

After shutdown, disconnect and restore power. Reconnect by SSH and repeat
`docker ps` and the topic check above **without running `docker-compose up` first**.
Both containers and the topics must recover automatically.

### 4. Check from the external computer

In a **local WSL terminal**, with the [WSL connection](real/SETUP.md#external-computer-and-wsl)
already prepared:

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=194 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
unset CYCLONEDDS_URI
ros2 topic list --no-daemon
rviz2 -d ~/ros2_ws/src/fastbot_ros2_docker/real/real_mapping.rviz
```

Check that the robot topics are visible and RViz2 displays the live `/map` with
**Fixed Frame = map** and **Global Status: Ok**. Use an existing viewer if one is
already open. Pi domain 0 and WSL domain 194 belong to this project's tested bridge setup.

## Verification and references

- [Grading Guide audit](GRADING_GUIDE_AUDIT.md): observed results and environment adaptations.
- [Cloud runtime](cloud_runtime.lock.json) and [simulation image digests](hub_release.lock.json).
- [Real-robot image digests](real/release.lock.json) and [runtime evidence summary](real/runtime.lock.json).
- [Asset provenance](course_assets.lock.json); upstream license markings are retained.
- [Historical engineering notes in Chinese](docs/engineering_notes.zh.md).

Functional checks have been performed; official grading has not been submitted.
Keep `.env`, credentials, and `runtime_logs/` out of Git.
