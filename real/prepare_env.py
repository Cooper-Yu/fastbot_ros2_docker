#!/usr/bin/env python3
"""Prepare this robot's device paths without opening or commanding hardware."""

import os
import platform
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src" / "serial_motor"))
from serial_motor.device_paths import (
    LIDAR_USB_IDS,
    MOTOR_USB_IDS,
    resolve_serial_device,
)


def main():
    if platform.machine() not in {"aarch64", "arm64"}:
        raise RuntimeError("Run device preparation on the ARM64 FastBot computer")
    target = ROOT / ".env"
    if target.exists():
        raise FileExistsError(
            "real/.env already exists. Review the existing run before changing it"
        )
    motor = resolve_serial_device("", "arduino_nano", MOTOR_USB_IDS)
    lidar = resolve_serial_device("", "lslidar", LIDAR_USB_IDS)
    camera = Path("/dev/video0")
    if not camera.exists():
        raise FileNotFoundError(camera)
    values = {
        "CP23_RUN_ID": str(uuid.uuid4()),
        "ROS_BASE": os.environ.get(
            "ROS_BASE",
            "ros@sha256:d9bcf2e6f72df127fdee07048c2e87b1b4b9a59a74af0592f4489fc2844aa855",
        ),
        "ROS_DOMAIN_ID": "0",
        "MOTOR_DEVICE": motor,
        "LIDAR_DEVICE": lidar,
        "CAMERA_DEVICE": str(camera),
    }
    with target.open("x") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")
    print(f"Prepared {target}. No hardware command was sent.")


if __name__ == "__main__":
    main()
