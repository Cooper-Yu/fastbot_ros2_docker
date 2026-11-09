# Task 2: Real-Robot Grading Checks

Download the repository as described in the [project README](../README.md#1-download-the-repository).
The robot must already have Docker, the two images and its device configuration.
For a new robot, use [SETUP.md](SETUP.md) once before these checks.

## 1. Start the containers

On the computer, connect to the FastBot:

```bash
ssh yg-fastbot@yg-fastbot.local
```

On the robot:

```bash
cd ~/ros2_ws/src/fastbot_ros2_docker/real
docker-compose up
```

Keep this terminal running. In another SSH terminal, run `docker ps` and check that
`fastbot-ros2-real` and `fastbot-ros2-slam-real` are running.

## 2. Check topics inside the robot

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
unset CYCLONEDDS_URI
ros2 topic list --no-daemon
```

Required topics: `/fastbot/scan`, `/fastbot_camera/image_raw` and `/fastbot/cmd_vel`.
Also check `/map` for the following external-map test.

## 3. Check power-on recovery

Leave the containers running and execute `sudo poweroff` on the Pi. After shutdown,
disconnect and restore power. Reconnect by SSH and repeat `docker ps` and the topic
check above. Do not start the containers manually: they must recover automatically.

## 4. Check topics and map outside the robot

The tested WSL connection must already be running; its one-time setup is in
[SETUP.md](SETUP.md#external-computer-and-wsl).
In a **local WSL terminal, not a Pi SSH terminal**:

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=194 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
unset CYCLONEDDS_URI
ros2 topic list --no-daemon
rviz2 -d ~/ros2_ws/src/fastbot_ros2_docker/real/real_mapping.rviz
```

Check that the robot topics are visible and RViz2 displays the live map with
**Global Status: Ok** and **Fixed Frame = map**. Inspect an already-open viewer
instead of launching another one.
