#!/usr/bin/env bash
set -e

# Coach support: load ROS before enabling unset-variable checks.
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
set -u -o pipefail

# Coach support: put each background service in its own process group.
# This also lets cleanup stop the child started by `ros2 run`.
set -m
service_pids=()
cleanup() {
  local exit_code=$?
  local service_pid
  local remaining
  trap - EXIT INT TERM
  for service_pid in "${service_pids[@]}"; do
    kill -TERM -- "-$service_pid" 2>/dev/null || true
  done
  for remaining in {1..50}; do
    local alive=false
    for service_pid in "${service_pids[@]}"; do
      if kill -0 -- "-$service_pid" 2>/dev/null; then alive=true; fi
    done
    if [ "$alive" = false ]; then break; fi
    sleep 0.1
  done
  for service_pid in "${service_pids[@]}"; do
    kill -KILL -- "-$service_pid" 2>/dev/null || true
    wait "$service_pid" 2>/dev/null || true
  done
  exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 0' INT TERM

# Learner implementation (CP23-C028): kept unchanged after review.
if [ "${CP23_FULL_DASHBOARD:-1}" = 1 ]; then
  # Coach support: static HTTP service extended with atomic waypoint storage.
  python3 /webapp/server.py 8000 --data-dir /data &
else
  python3 -m http.server 8000 --bind 0.0.0.0 --directory /webapp &
fi
# Coach support: remember the process for waiting and cleanup.
service_pids+=("$!")

# Learner implementation (CP23-C029): kept unchanged after repair.
ros2 run rosbridge_server rosbridge_websocket --ros-args -p address:=0.0.0.0 -p port:=9090 &
service_pids+=("$!")

# Coach support: manual driving is opt-in for this isolated simulation only.
if [ "${CP23_ENABLE_SIM_MANUAL:-0}" = 1 ]; then
  if [ "${CP23_FULL_DASHBOARD:-1}" = 1 ]; then
    python3 /usr/local/bin/camera_relay.py &
    service_pids+=("$!")
    python3 /usr/local/bin/dashboard_adapter.py --ros-args \
      -p use_sim_time:=true -p navigation_enabled:=${CP23_ENABLE_NAVIGATION:-false} \
      -p odom_frame:=fastbot_odom -p base_frame:=fastbot_base_footprint \
      -p scan_topic:=/fastbot/scan -p odom_topic:=/fastbot/odom \
      -p cmd_vel_topic:=/fastbot/cmd_vel \
      -p linear_limit:=0.05 -p angular_limit:=0.30 &
  else
    python3 /usr/local/bin/manual_bridge.py &
  fi
  service_pids+=("$!")
fi
if [ "${CP23_ENABLE_NAVIGATION:-false}" = true ]; then
  ros2 launch /dashboard/navigation.launch.py &
  service_pids+=("$!")
fi
# Coach support: a running process is not proof that it accepts connections.
python3 /usr/local/bin/check_web_services.py --timeout 15

# Coach support: keep the container alive, and fail if either service exits.
set +e
wait -n "${service_pids[@]}"
service_exit=$?
set -e
printf 'Web service exited unexpectedly (status %s).\n' "$service_exit" >&2
if [ "$service_exit" -eq 0 ]; then service_exit=1; fi
exit "$service_exit"