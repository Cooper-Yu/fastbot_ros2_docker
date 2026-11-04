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
python3 -m http.server 8000 --bind 0.0.0.0 --directory /webapp &
# Coach support: remember the process for waiting and cleanup.
service_pids+=("$!")

# Learner implementation (CP23-C029): kept unchanged after repair.
ros2 run rosbridge_server rosbridge_websocket --ros-args -p address:=0.0.0.0 -p port:=9090 &
service_pids+=("$!")

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