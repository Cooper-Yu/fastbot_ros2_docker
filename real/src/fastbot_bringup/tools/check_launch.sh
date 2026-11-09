#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source "$HOME/ros2_ws/install/setup.bash"
set -u
export ROS_DOMAIN_ID=121
export ROS_LOCALHOST_ONLY=1
timeout --signal=TERM --kill-after=5 35 python3 "$HOME/.cache/cp21-delegated/check_launch.py"
