#!/usr/bin/env bash
set -e

# Coach support: load the base ROS environment.
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash

# TODO(CP23-C007): Load the course workspace environment from /ros2_ws/install.
# Add one source command below.
source /ros2_ws/install/setup.bash
# Coach support: run the supplied command after preparing the environment.
exec "$@"
