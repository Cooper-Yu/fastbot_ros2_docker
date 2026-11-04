#!/usr/bin/env bash
set -e -o pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/runtime_logs/dashboard_$(date -u +%Y%m%dT%H%M%SZ)_$(cat /proc/sys/kernel/random/uuid)"
STATE="$ROOT/runtime_logs/dashboard_state"
mkdir -p "$OUT" "$STATE"
if [ ! -f "$STATE/waypoints.json" ];then cp "$ROOT/simulation/dashboard/data/waypoints.json" "$STATE/waypoints.json";fi
if [ ! -d "$STATE/maps" ];then cp -a "$ROOT/simulation/dashboard/data/maps" "$STATE/maps";fi
printf 'root:x:0:0:root:/root:/bin/bash\ncp23:x:1000:1000:CP23:/tmp:/bin/bash\n' > "$OUT/probe-passwd"
SECONDS_LIMIT="${CP23_SESSION_SECONDS:-1800}"
if ! [[ "$SECONDS_LIMIT" =~ ^[1-9][0-9]*$ ]];then echo 'CP23_SESSION_SECONDS must be positive' >&2;exit 2;fi
RUN=$(cat /proc/sys/kernel/random/uuid)
NET="cp23-navigation-$RUN"
GIMAGE=$(docker image inspect -f '{{.Id}}' cp23-local/gazebo-axis:20261104)
WIMAGE=$(docker image inspect -f '{{.Id}}' cp23-local/web-navigation:20261104)
GCID='';WCID='';RPID='';NETWORK_CREATED=false
echo "$RUN" > "$OUT/run-id.txt"
test "$(docker info -f '{{.ID}}')" = 76a71b5d-f88e-432d-95a8-85bc6a1040cd
cleanup(){
 code=$?;trap - EXIT
 for role in web gazebo;do
  case "$role" in web) cid="$WCID";;gazebo) cid="$GCID";;esac
  if [ -n "$cid" ];then
   test "$(docker inspect -f '{{index .Config.Labels "codex.run"}}' "$cid")" = "$RUN"
   docker stop --signal SIGINT --time 20 "$cid" > "$OUT/$role-stop.txt" 2>&1 || true
   docker logs "$cid" > "$OUT/$role.stdout" 2> "$OUT/$role.stderr" || true
   docker inspect "$cid" > "$OUT/$role-final.json"
   if [ "$(docker inspect -f '{{.State.Running}}' "$cid")" = false ];then docker rm "$cid" > "$OUT/$role-removed.txt";else code=91;fi
  fi
 done
 if [ -n "$RPID" ];then wait "$RPID" 2>/dev/null || true;fi
 if [ "$NETWORK_CREATED" = true ];then docker network inspect "$NET" > "$OUT/network-final.json";docker network rm "$NET" > "$OUT/network-removed.txt";fi
 docker ps -a --filter "label=codex.run=$RUN" --format '{{.ID}} {{.Status}}' > "$OUT/remaining-containers.txt"
 echo "$code" > "$OUT/result-exit.txt"
 echo "NAVIGATION_CLEANED $RUN EXIT=$code"
 exit "$code"
}
trap cleanup EXIT
trap 'exit 0' INT TERM
docker network create --driver bridge --label codex.owner=cp23-dashboard-local --label codex.project=checkpoint23-docker-for-robotics --label "codex.run=$RUN" "$NET" > "$OUT/network-id.txt"
NETWORK_CREATED=true
COMMON=(--network "$NET" --label codex.owner=cp23-dashboard-local --label codex.project=checkpoint23-docker-for-robotics --label "codex.run=$RUN" --user 1000:1000 --read-only --cap-drop ALL --security-opt no-new-privileges --log-opt max-size=20m --log-opt max-file=1 --env HOME=/tmp --env ROS_LOG_DIR=/tmp/ros-logs --env ROS_DOMAIN_ID=187 --env ROS_LOCALHOST_ONLY=0)
GCID=$(docker create --name "cp23-nav-gazebo-$RUN" "${COMMON[@]}" --cpus 4 --memory 4g --pids-limit 512 --shm-size 256m --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 --tmpfs /run/user/1000:rw,nosuid,nodev,size=8m,mode=700,uid=1000,gid=1000 --mount type=bind,src=/mnt/wslg/.X11-unix,dst=/tmp/.X11-unix,readonly --mount "type=bind,src=$OUT/probe-passwd,dst=/etc/passwd,readonly" --env DISPLAY=:0 --env XDG_RUNTIME_DIR=/run/user/1000 --env QT_X11_NO_MITSHM=1 --env LIBGL_ALWAYS_SOFTWARE=1 --env LP_NUM_THREADS=2 --env OMP_NUM_THREADS=2 --env OPENBLAS_NUM_THREADS=2 --env GAZEBO_IP=127.0.0.1 --env GAZEBO_MODEL_DATABASE_URI= "$GIMAGE" ros2 launch fastbot_gazebo one_fastbot_room.launch.py headless:=1)
echo "$GCID" > "$OUT/gazebo-cid.txt"
docker inspect "$GCID" > "$OUT/gazebo-created.json"
docker start "$GCID"
docker exec --env "CP23_MAP_REFERENCE=$(cat "$STATE/maps/PROVENANCE.json")" -i "$GCID" /usr/local/bin/entrypoint_gazebo.sh python3 - < "$ROOT/simulation/dashboard/measured_initial_pose.py" > "$OUT/observed-initial-pose.json" 2> "$OUT/initial.stderr"
cp "$OUT/observed-initial-pose.json" "$STATE/maps/navigation_initial_pose.json"
WCID=$(docker create --name "cp23-nav-web-$RUN" "${COMMON[@]}" --cpus 4 --memory 3g --pids-limit 512 --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777 --env CP23_FULL_DASHBOARD=1 --env CP23_ENABLE_SIM_MANUAL=1 --env CP23_ENABLE_NAVIGATION=true --mount "type=bind,src=$STATE,dst=/data" --publish 127.0.0.1:18000:8000 --publish 127.0.0.1:19090:9090 "$WIMAGE")
echo "$WCID" > "$OUT/web-cid.txt"
docker inspect "$WCID" > "$OUT/web-created.json"
docker start "$WCID"
echo "FastBot dashboard: http://127.0.0.1:18000/ ; ROSbridge ws://127.0.0.1:19090"
echo "Records: $OUT ; persistent data: $STATE ; stop with Ctrl+C"
for ((tick=0;tick<SECONDS_LIMIT;tick++));do
 if [ -f "$OUT/stop.request" ];then exit 0;fi
 if [ "$(docker inspect -f '{{.State.Running}}' "$WCID")" != true ];then exit 4;fi
 sleep 1
done
echo "Session observation limit reached; stopping owned containers."
exit 0