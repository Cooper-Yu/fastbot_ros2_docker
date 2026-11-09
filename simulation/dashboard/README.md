# FastBot Web Dashboard and Saved-Map Navigation

This optional local profile adapts the CP22 reference dashboard to the CP23
simulation. It is engineering support, not an independent learner implementation
or an official grading result. Asset origins are recorded in
[webapp_assets.lock.json](../../webapp_assets.lock.json) and
[MODEL-PROVENANCE.json](../webapp/fastbot_webapp/assets/MODEL-PROVENANCE.json).

## Features

- English map, 3D robot, camera, measured pose/speed, joystick, waypoints and task status.
- URDF expanded from the simulation Xacro, original STL meshes and real joint states.
- A fixed root transform reconciles the original CAD forward axis with ROS drive coordinates.
- Saved occupancy-grid maps preserve unknown cells and have round-trip verification data.
- Bounded ROSbridge fragment reassembly supports the 800×800 camera stream.
- Manual input is limited to 0.05 m/s and 0.30 rad/s, with input/feedback watchdogs.

Historical exploration covered 99.52% of non-solid cells in the reference room
slice over 13 segments and approximately 21.32 m of travel. Furniture interiors
and occluded cells remain unknown; this does not prove every robot-sized position
is reachable. The camera is a 2D display; its legacy frame naming is not a
validated 3D optical-projection interface. This profile is for simulation.

## Run locally

From the repository root in WSL Ubuntu-22.04:

```bash
docker build -f simulation/Dockerfile.gazebo -t cp23-local/gazebo-axis:20261104 .
docker build -f simulation/Dockerfile.webapp -t cp23-local/web-dashboard:20261104 .
docker build -f simulation/Dockerfile.dashboard-support -t cp23-local/web-navigation:20261104 .
bash simulation/dashboard/run_local.bash
```

The historical launcher includes an engine-identity guard for its validated local
Docker installation. Review that environment before reusing the launcher on
another engine; do not treat it as the cloud Grading Guide entry point.

Open <http://127.0.0.1:18000/> and click **Connect**. Startup does not command motion.
**Go** requests navigation only for a waypoint associated with the confirmed map;
saving a waypoint does not move the robot. Stop with `Ctrl+C`. The default
observation window is 1800 seconds, configurable with `CP23_SESSION_SECONDS`.
Run logs are kept under `runtime_logs/dashboard_*`; persistent maps and waypoints
are under `runtime_logs/dashboard_state`.

This saved-map profile runs Gazebo plus a Nav2-enabled Web container. The course
Task 1 live-mapping profile instead uses Gazebo, Cartographer SLAM and Web as
three services. Do not run Cartographer and AMCL as competing map-localization
providers for the same robot.

## Evidence and checks

- Fragment contract: `node tests/rosbridge-fragments.mjs` from the repository root.
- Raw grid: `data/maps/room.raw.grid.json`; saved-map comparison: `data/maps/ROUNDTRIP.json`.
- Historical final local run: `dashboard_20261104T144127Z` in the local runtime logs.
- Current course checks: [Grading Guide audit](../../GRADING_GUIDE_AUDIT.md).

The historical local navigation run reached Living room, Doorway and Bedroom with
0.15 m / 0.2 rad arrival limits. Native release and a separate disconnect test both
produced zero output and measured stop. These observations are bounded test
results, not hard real-time or real-robot guarantees. If a reloaded page reports
`succeeded-unowned`, confirm task completion and stop before using **Reconcile idle**;
do not resend the previous goal automatically.
