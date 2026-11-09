# Task 2: FastBot Real-Robot Containers

## Requirements

- ARM64 FastBot computer running Ubuntu 22.04, with Docker and Compose V2 installed.
- Motor controller, N10 LiDAR and camera connected.
- Current user can access Docker; the Docker system service is enabled at boot.
- Tested device profile: application UID/GID `1000:1000`, `dialout=20`, `video=44`.

The two containers run ROS 2 Humble. The driver container publishes real scan,
image, odometry and TF data; Cartographer consumes scan/odometry and publishes
`/map`. Both use host networking and ROS domain 0.

## Download, configure and start

```bash
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
git clone https://github.com/Cooper-Yu/fastbot_ros2_docker.git
cd fastbot_ros2_docker/real
python3 prepare_env.py
```

For an existing checkout, enter its `real` directory. `prepare_env.py` refuses to
overwrite an existing `.env`; retain and review that file. Verify the detected
serial paths, camera device, run identifier and ARM64 base image reference.
Preparation does not open or command the devices.

For the guide's command spelling, use the wrapper only if necessary:

```bash
if ! command -v docker-compose >/dev/null 2>&1; then
  install -D -m 755 docker-compose "$HOME/.local/bin/docker-compose"
fi
export PATH="$HOME/.local/bin:$PATH"
sudo systemctl enable --now docker
docker-compose up
```

Keep that terminal running. In another terminal:

```bash
docker ps
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ros2 topic list
```

Expect `fastbot-ros2-real` and `fastbot-ros2-slam-real`, plus topics
`/fastbot/scan`, `/fastbot_camera/image_raw`, `/fastbot/cmd_vel` and `/map`.

To explicitly download the published images before starting:

```bash
docker compose pull
docker compose up --no-build
```

For a source build instead:

```bash
docker compose build
docker compose up
```

`ROS_BASE` in `.env` must identify the verified ARM64 base image.
Fixed source revisions and image digests are in [source.lock.json](source.lock.json)
and [release.lock.json](release.lock.json).

## Power-on recovery

Both services use `restart: unless-stopped`. Leave them running before shutdown:

```bash
sudo poweroff
```

After shutdown, disconnect and restore power. Reconnect by SSH and check
`docker ps` and the topics without running `up` first. Deliberately stopped
containers need to be started again before testing this behavior.

## External computer and WSL

On a computer with working direct DDS connectivity, use the same ROS domain and
compatible middleware, run `ros2 topic list`, and open RViz2 with
**Fixed Frame = map** and a Map display subscribed to `/map`.

The tested Windows/WSL setup uses a separate Zenoh bridge because WSL NAT can
prevent direct DDS discovery. The Pi remains on domain 0; the WSL viewer uses
194. This bridge is an optional network helper, separate from the two application
containers. It carries real ROS data and can also forward ROS commands.

On the Pi, from this directory:

```bash
docker compose --env-file .env -f compose.wsl-link.yaml up -d
```

On WSL Ubuntu-22.04, install ROS 2 Humble, RViz2 and
`ros-humble-rmw-cyclonedds-cpp`. From the repository root:

```bash
docker pull --platform linux/amd64 eclipse/zenoh-bridge-ros2dds@sha256:74fae6a9d4f449c53d1ee6f0faaca97d01c1e68dfcafd785b657f01907157d22
python3 real/wsl_viewer.py prepare
source /opt/ros/humble/setup.bash
python3 real/wsl_viewer.py run --robot FASTBOT_IP
```

Replace `FASTBOT_IP` with the robot's current address. Use one viewer instance;
closing its RViz window stops the bridge process it owns. Preparation extracts and
checks runtime files under `runtime_logs/wsl_bridge` without a global musl install.

In another WSL terminal:

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=194 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ros2 topic list
python3 real/check_runtime.py
```

Check live map and TF data in RViz2. Do not reuse the Pi's domain-0 settings in
this WSL bridge terminal. The current map contains only observed space; the robot
model uses the inherited CP21 approximation, with no new extrinsic calibration.

## Records

[Runtime summary](runtime.lock.json) records the hardware and power-cycle checks.
[Historical engineering notes in Chinese](ENGINEERING_NOTES.zh.md) retain earlier
investigation details. Official grading has not been submitted.
