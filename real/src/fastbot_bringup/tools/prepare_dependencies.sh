#!/usr/bin/env bash
# User-run prerequisite installation. No serial devices, boot edits or reboot.
set -euo pipefail
sudo apt-get update
sudo apt-get install -y ros-humble-v4l2-camera ros-humble-image-transport-plugins \
  v4l-utils libpcap-dev ros-humble-diagnostic-updater ros-humble-pcl-conversions \
  ros-humble-teleop-twist-keyboard
echo 'Dependencies installed. Camera boot configuration has not been changed.'
