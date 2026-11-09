# Local Three-Container Mapping

Target: WSL Ubuntu-22.04, ROS 2 Humble and Gazebo Classic 11.
`compose.yaml` defines the three application services. `compose.local.yaml`,
`local_passwd` and `run_compose_local.bash` provide the local runtime wiring.
This profile is separate from the two-container saved-map navigation profile.

## Build the images

From the repository root:

```bash
CP23_RUN_ID=build-only docker compose -p cp23-course-local -f simulation/compose.yaml -f simulation/compose.local.yaml build
```

## Start and stop

```bash
bash simulation/run_compose_local.bash
```

The launcher creates a run identifier and records configuration/image identities.
Its default observation window is 1800 seconds. Set a positive
`CP23_SESSION_SECONDS` to change it. Stop with `Ctrl+C` or the run log directory's
`stop.request` file. This observation window is not an image-build timeout.
The launcher refuses to take over an existing run of the same project and uses
already-built images rather than downloading or building at application startup.

Open <http://127.0.0.1:18000/> and explicitly connect to
`ws://127.0.0.1:19090`. This profile runs live Cartographer mapping, without saved-map
Nav2 navigation. It uses ROS domain 193 and does not connect to physical hardware
or send motion automatically. The HTTP and ROSbridge ports must be available.

Gazebo uses `headless:=1`: there is no interactive Gazebo client window, while
camera rendering still uses the read-only WSLg X11 socket. CPU/memory limits are
Gazebo 4 cores/4 GiB, SLAM 2 cores/2 GiB and Web 3 cores/3 GiB. Applications run as
non-root UID 1000 with read-only filesystems, dropped capabilities and temporary
writable directories. Shutdown uses SIGINT with a 20-second grace period.
`local_passwd` is a synthetic UID mapping, not a host credential file.

The `web-data` named volume mounts at `/data`. Its project name is
`cp23-course-local_web-data`; removing containers/networks preserves it. New-volume
initialization and data persistence across container recreation were tested.
Do not remove the volume during routine shutdown.

## Verification scope

The 2026-11-05 local run verified three-image builds, real sensor data through
Cartographer `/map`, HTTP 200 responses and WebSocket map/JPEG delivery. Waypoint
data survived Web container recreation. The run ended with application exit 0,
no OOM, containers/networks removed and the volume retained.

That local run was stationary; it does not establish whole-room exploration,
real-robot behavior or an independent learner assessment. Later cloud joystick
checks are recorded separately in [the audit](../GRADING_GUIDE_AUDIT.md).
See [the runtime lock](../compose_runtime.lock.json) for local image/source identities.
