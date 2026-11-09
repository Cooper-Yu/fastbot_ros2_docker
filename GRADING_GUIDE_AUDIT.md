# CP23 Grading Guide Audit

Date: 2026-11-09 (Asia/Shanghai). Task 1 functional checks include the sustained
joystick CPU repair below. Task 2 has real-robot, power-cycle and external-WSL
evidence. Official grading has not been submitted. This report does not award a score.

Source: the course Task 1 and Task 2 Grading Guides. Repository:
https://github.com/Cooper-Yu/fastbot_ros2_docker. The actual Pi clone was verified
at revision `2b13efce5d036c3349fa76f5824f9d6fbdb30cdb`; later documentation/configuration
updates were fast-forwarded separately.

## Task 1

| Guide item | Result | Evidence and limits |
| --- | --- | --- |
| Enter `simulation` | VERIFIED | Original `cd` command executed in the cloud terminal |
| `docker-compose up` | VERIFIED_AFTER_ENVIRONMENT_REPAIR | Three fixed images pulled from Docker Hub; full GUI/camera profile started |
| `docker ps` | VERIFIED | All three application containers running; process/data checks supplement PID1 status |
| `docker images` | VERIFIED_AFTER_TAG_REPAIR | Digest-pulled images received their original readable tags after identity checks |
| Graphical Tools | VERIFIED | Room and FastBot visible; `gzserver` and `gzclient` alive, no OOM in the repaired run |
| `webpage_address` | VERIFIED | Returned URL opened in the dedicated browser |
| `rosbridge_address` | VERIFIED | Returned WSS URL connected; command channel verified |
| Web joystick | VERIFIED_AFTER_CPU_REPAIR | Native continuous hold for four seconds, real motion and release stop independently observed |
| Live map | VERIFIED | ROS map data and rendered grid observed; current session has unknown regions |

### Memory failure and recovery

The first cloud environment lacked Docker/Compose. These were installed and the
service/user-group setup completed before executing the guide commands.

The initial rosject had an outer `memory.max` of 2684354560 bytes (2.5 GiB), while
Gazebo's configured container limit was 4 GiB. A Gazebo child was killed despite
PID1 remaining alive. A softpipe/1800 MiB trial later lost `gzclient` as well.
Neither trial establishes a working full GUI configuration. Host `MemAvailable`
and PID1 `OOMKilled=false` were insufficient checks; original failures were retained.

After the user restored resources and reopened the rosject, the new boot ID was
`63cf56cf-da79-416c-b464-e04742848fff` and Docker engine ID was
`b8de34f7-15d6-4b74-84b2-449536536d96`. The visible outer memory limit was `max`.
The original full camera profile was restored. Gazebo used about 2.57 GB with
`gzserver`/`gzclient` alive and no OOM. Subscription status was not independently
established as the sole cause of the resource change.

A live probe received scan7/odom62/map3/clock62, with simulation time advancing
91.02 to 91.63 seconds and map171×88/5208 known cells. The browser displayed the
course model, measured pose and 800×800 camera. Slow simulation can make the camera
briefly show STALE; a constant wall-clock image rate is not claimed. This new
SLAM session is distinct from the saved local whole-room map.

### Sustained joystick failure and CPU repair

Short motion/release tests initially passed, but the user's sustained-control
retest exposed a failure: a three-second native hold was released after about
0.83 seconds with `Manual control permission lost` and
`Measured feedback invalid or stale; output zero`. Only a few millimetres of motion
occurred. The browser remained focused and visible. Short motion alone did not
establish correct sustained control; that conclusion was reopened for repair.

A 22-second baseline probe found scan42/odom424. Scan receipt intervals averaged
0.514 seconds, reached 0.698 seconds, and exceeded 0.5 seconds 21 times. At failed
checks, odometry and TF remained valid; scan source age was only about
0.08–0.095 simulation seconds, but actual scan receipt age exceeded 0.5 seconds.
Gazebo had a 2-core quota and 8249/8298 accumulated throttled CPU periods.

Only that running Gazebo container's CPU quota changed from 2 to 4 cores. The
same scene, 800×800 camera and image contents remained in use; the 0.5-second
feedback limit and 0.3-second command watchdog were retained. The comparison
received scan82/odom824, with average/max scan intervals of 0.257/0.377 seconds,
zero intervals above 0.5 seconds, and invalid-feedback status samples falling
from 6 to 0. Observed real-time factor improved from 0.193 to 0.390.

The four-second native joystick hold then produced 81 nonzero final velocity
commands, a maximum command of 0.0378205 m/s and 2498 odometry samples. Independent
odometry showed approximately 6 cm of movement and a measured final stop; the last
five commands were zero. The webpage showed 0.008→0.060 m, with no feedback-loss
transition during the hold. All three containers and both Gazebo processes
remained alive, with no OOM. Local and cloud Compose files both retain the 4-core
configuration and have identical SHA256. This is an observed repair under the
tested instance load, not a hard real-time guarantee.

Evidence is retained in the ignored local directory
`runtime_logs/grading_guide_20261109`: `cpu4-repair-receipt.json`,
`cpu4-hold4s-trace.json`, earlier failure traces and native screenshots.
Cloud preparation and runtime logs are under `subscription_resume`. Proxy capability
URLs are not committed. Current identities are in [cloud_runtime.lock.json](cloud_runtime.lock.json).

## Task 2

| Guide item | Result | Evidence and limits |
| --- | --- | --- |
| README download/start instructions | VERIFIED | Public repository address and simulation/robot configuration documented |
| `git clone` | VERIFIED | Actual HTTPS clone into the Pi's standard source directory, revision `2b13efc` |
| `docker-compose up` | VERIFIED_WITH_ENVIRONMENT_ADAPTATION | Guide spelling uses a user-level Compose V2 wrapper; verified cached images used |
| `docker ps` | VERIFIED | Both application containers running; optional network bridge and platform RRL identified separately |
| Laser topic | VERIFIED | `/fastbot/scan` |
| Camera topic | VERIFIED | `/fastbot_camera/image_raw` |
| Velocity-command topic | VERIFIED | `/fastbot/cmd_vel`; no robot motion commanded in this audit |
| Power-on automatic startup | VERIFIED | New boot ID, same application CIDs, new start times, running/no OOM |
| External topics | VERIFIED | Native WSL `ros2 topic list`, 25 topics |
| RViz2 map | VERIFIED | Native WSL window, Global Status: Ok, new map and actual TF |

The original Pi project was preserved under
`/home/yg-fastbot/cp23_grading_backups/20261109-6d92f2/prior-project` before the
actual clone. Only the reviewed local `.env` was copied to retain device/run settings.
The power-cycle boot IDs changed from `1b0bc28f-4222-42df-8eb0-841a3ebeaca6` to
`1b382028-edb1-4cff-b68b-2cae6fe24373`. Both applications started at
2026-11-09T05:53:36Z, with Docker enabled and `restart: unless-stopped`.
WSL received scan13/image32/odom22/map3/tf162; map81×99 had 3674 known cells,
with zero measured speed and no command publisher in that stationary probe.

The subsequent user-led checks confirmed automatic container startup and recovery
of the sensor/map topics after another power cycle. A Husarnet-specific inherited
`CYCLONEDDS_URI` initially hid the robot topics in the Pi shell; unsetting it for
the current terminal restored discovery. WSL domain194 topic discovery was also
confirmed. The user-led RViz check remains a separate final observation; earlier
native RViz evidence is retained.

See [real/runtime.lock.json](real/runtime.lock.json) and the ignored audit directory
for clone, command, power-cycle, external-data and screenshot records.
Formal grading: **NOT_SUBMITTED**. Reduced-help independent check: **SKIPPED_BY_USER**.
