#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source "$HOME/ros2_ws/install/setup.bash"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///var/lib/theconstruct.rrl/cyclonedds_husarnet.xml
export ROS_LOCALHOST_ONLY=0
export ROS_DOMAIN_ID=0
export CP21_REMOTE_MODE="$1"
export CP21_REMOTE_TOPIC="$2"
set -u
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
timeout --signal=INT --kill-after=5 95 python3 "$script_dir/check_remote_keyboard_host.py"
