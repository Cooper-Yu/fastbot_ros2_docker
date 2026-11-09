#!/usr/bin/env python3
"""Prepare and run a native WSL viewer for the real FastBot."""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "runtime_logs/wsl_bridge"
IMAGE = (
    "eclipse/zenoh-bridge-ros2dds@sha256:"
    "74fae6a9d4f449c53d1ee6f0faaca97d01c1e68dfcafd785b657f01907157d22"
)
FILES = {
    "zenoh-bridge-ros2dds": (
        "/zenoh-bridge-ros2dds",
        "add0fbfe3b6f22b5c2ddaa4dadaa366bd540e43c5aa73cd35a3b28aa3dc4d47f",
    ),
    "ld-musl-x86_64.so.1": (
        "/lib/ld-musl-x86_64.so.1",
        "38d022ce7425ff105ccfb53598f606e6e5f5f0a34bfbc793d65e6f34c9d72806",
    ),
    "libgcc_s.so.1": (
        "/usr/lib/libgcc_s.so.1",
        "5ea51dd885b6fc691eccc569d0bda739204204f6161e97075b26dc9c050d1ca1",
    ),
}


def verify():
    """Verify native files against the reviewed official amd64 image."""
    for name, (_, expected) in FILES.items():
        if hashlib.sha256((CACHE / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("Bridge file hash differs: " + name)


def prepare():
    """Extract three pinned image files without starting a container."""
    CACHE.mkdir(parents=True, exist_ok=True)
    if all((CACHE / name).exists() for name in FILES):
        verify()
        return
    subprocess.run(
        ["docker", "image", "inspect", "--platform", "linux/amd64", IMAGE],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    run_id = str(uuid.uuid4())
    cid = subprocess.check_output(
        [
            "docker",
            "create",
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--read-only",
            "--label",
            "codex.owner=cp23-wsl-viewer",
            "--label",
            "codex.run=" + run_id,
            IMAGE,
            "--help",
        ],
        text=True,
    ).strip()
    receipt = json.loads(subprocess.check_output(["docker", "inspect", cid]))[0]
    (CACHE / "extraction-receipt.json").write_text(json.dumps(receipt, indent=2))
    try:
        for name, (source, _) in FILES.items():
            subprocess.run(
                ["docker", "cp", "-L", cid + ":" + source, str(CACHE / name)],
                check=True,
            )
        verify()
        (CACHE / "ld-musl-x86_64.so.1").chmod(0o755)
        (CACHE / "zenoh-bridge-ros2dds").chmod(0o755)
    finally:
        current = json.loads(subprocess.check_output(["docker", "inspect", cid]))[0]
        if current["Config"]["Labels"].get("codex.run") != run_id:
            raise RuntimeError("Extraction container ownership changed")
        subprocess.run(["docker", "rm", cid], check=True)


def native_command():
    return [
        str(CACHE / "ld-musl-x86_64.so.1"),
        "--library-path",
        str(CACHE),
        str(CACHE / "zenoh-bridge-ros2dds"),
    ]


def run_viewer(robot):
    """Keep the local bridge alive for RViz, then clean up this child only."""
    verify()
    if os.environ.get("ROS_DISTRO") != "humble":
        raise RuntimeError("First source /opt/ros/humble/setup.bash")
    env = dict(
        os.environ,
        ROS_DOMAIN_ID="194",
        ROS_LOCALHOST_ONLY="0",
        RMW_IMPLEMENTATION="rmw_cyclonedds_cpp",
        ROS_DISTRO="humble",
    )
    cmd = native_command() + [
        "client",
        "-d",
        "194",
        "-e",
        "tcp/" + robot + ":17447",
        "--no-multicast-scouting",
    ]
    with (CACHE / "bridge.log").open("w") as log:
        child = subprocess.Popen(
            cmd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            time.sleep(2)
            if child.poll() is not None:
                raise RuntimeError(
                    "Bridge exited; inspect runtime_logs/wsl_bridge/bridge.log"
                )
            subprocess.run(
                ["rviz2", "-d", str(ROOT / "real/real_mapping.rviz")],
                env=env,
                check=True,
            )
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
                child.wait(timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "version", "run"])
    parser.add_argument("--robot", default="192.168.1.73")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "version":
        verify()
        subprocess.run(native_command() + ["--version"], check=True)
    else:
        run_viewer(args.robot)


if __name__ == "__main__":
    main()
