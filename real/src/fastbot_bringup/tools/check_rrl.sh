#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source "$HOME/ros2_ws/install/setup.bash"
set -u
timeout --signal=TERM --kill-after=5 75 python3 "$(dirname -- "${BASH_SOURCE[0]}")/check_rrl.py"
