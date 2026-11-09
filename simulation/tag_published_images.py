#!/usr/bin/env python3
"""Restore readable image tags after the course's digest-pinned cloud pull."""

import json
import subprocess
from pathlib import Path


def inspect(reference):
    result = subprocess.run(
        ["docker", "image", "inspect", reference],
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def main():
    root = Path(__file__).resolve().parent.parent
    release = json.loads((root / "hub_release.lock.json").read_text())
    results = []
    for item in release["images"]:
        target = item["target"]
        pinned = release["repository"] + "@" + item["push_digest"]
        source = inspect(pinned)
        if source is None or pinned not in source.get("RepoDigests", []):
            raise RuntimeError("Pull and verify the pinned image first: " + pinned)
        existing = inspect(target)
        if existing is not None and existing["Id"] != source["Id"]:
            raise RuntimeError("Existing tag points to different content: " + target)
        if existing is None:
            subprocess.run(["docker", "tag", pinned, target], check=True)
        tagged = inspect(target)
        assert tagged["Id"] == source["Id"]
        assert tagged["RootFS"] == source["RootFS"]
        results.append(
            {
                "tag": target,
                "digest": item["push_digest"],
                "id": tagged["Id"],
                "verified": True,
            }
        )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
