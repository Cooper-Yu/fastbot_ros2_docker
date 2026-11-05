#!/usr/bin/env bash
# Coach support: public bounded launcher; no build or installation at runtime.
set -e -o pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
RUN=$(cat /proc/sys/kernel/random/uuid)
OUT="$ROOT/runtime_logs/compose_local_$(date -u +%Y%m%dT%H%M%SZ)_$RUN"
mkdir -p "$OUT"
export CP23_RUN_ID="$RUN"
PROJECT=cp23-course-local
C=(docker compose -p "$PROJECT" -f simulation/compose.yaml -f simulation/compose.local.yaml)
LIMIT="${CP23_SESSION_SECONDS:-1800}"
[[ "$LIMIT" =~ ^[1-9][0-9]*$ ]] || exit 2
test "$(docker info -f '{{.ID}}')" = 76a71b5d-f88e-432d-95a8-85bc6a1040cd
test -d /mnt/wslg/.X11-unix
test -z "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")"
printf '%s\n' "$RUN" > "$OUT/run-id.txt"
"${C[@]}" config --format json > "$OUT/config.json"
for image in fastbot-ros2-gazebo:local fastbot-ros2-slam:local fastbot-ros2-webapp:local;do
 docker image inspect "$image" >> "$OUT/images.json"
done
cleanup(){
 code=$?;trap - EXIT
 docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" > "$OUT/cids.txt"
 while read -r cid;do
  [ -n "$cid" ] || continue
  if [ "$(docker inspect -f '{{index .Config.Labels "codex.run"}}' "$cid")" != "$RUN" ];then
   echo 'Ownership mismatch; no cleanup performed' >&2;exit 90
  fi
 done < "$OUT/cids.txt"
 "${C[@]}" stop --timeout 20 > "$OUT/stop.stdout" 2> "$OUT/stop.stderr" || code=91
 while read -r cid;do
  [ -n "$cid" ] || continue
  docker inspect "$cid" > "$OUT/$cid-final.json"
  docker logs "$cid" > "$OUT/$cid.stdout" 2> "$OUT/$cid.stderr" || true
  test "$(docker inspect -f '{{.State.Running}}' "$cid")" = false || exit 92
 done < "$OUT/cids.txt"
 "${C[@]}" down --timeout 20 > "$OUT/down.stdout" 2> "$OUT/down.stderr" || code=93
 docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" > "$OUT/remaining.txt"
 docker volume inspect "${PROJECT}_web-data" > "$OUT/preserved-volume.json" || true
 echo "$code" > "$OUT/result-exit.txt"
 echo "COMPOSE_CLEANED EXIT=$code; volume retained; records=$OUT"
 exit "$code"
}
trap cleanup EXIT
trap 'exit 0' INT TERM
"${C[@]}" up -d --no-build --pull never > "$OUT/up.stdout" 2> "$OUT/up.stderr"
"${C[@]}" ps --format json > "$OUT/ps.json"
echo "COMPOSE_READY records=$OUT"
echo 'Dashboard http://127.0.0.1:18000/ ; ROSbridge ws://127.0.0.1:19090 ; Ctrl+C stops owned services.'
for ((tick=0;tick<LIMIT;tick++));do
 [ ! -f "$OUT/stop.request" ] || exit 0
 count=$(docker ps -q --filter "label=codex.run=$RUN" | wc -l)
 [ "$count" = 3 ] || exit 4
 sleep 1
done
