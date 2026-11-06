#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    manifest = json.loads((ROOT / "artifacts" / "agent300-manifest.json").read_text())
    config = json.loads((ROOT / "artifacts" / "agent300-run-config.json").read_text())
    keys = json.loads((ROOT / "runtime" / "agent300-keys.json").read_text())
    cve = json.loads((ROOT / "artifacts" / "agent300-cve-manifest.json").read_text())
    cve_input = json.loads((ROOT / "runtime" / "cve-input.json").read_text())
    if len(set(keys.values())) != len(keys):
        raise SystemExit("project keys must be unique by value as well as by project")
    if len(manifest) != 300 or len(config["repositories"]) != 300:
        raise SystemExit("corpus must contain exactly 300 repositories")
    if sum(item["development"] for item in manifest) != 100:
        raise SystemExit("expected exactly 100 development repositories")
    if sum(not item["development"] for item in manifest) != 200:
        raise SystemExit("expected exactly 200 held-out repositories")
    if not all(item.get("sha") for item in manifest):
        raise SystemExit("every repository must have a fixed SHA")
    if set(config["repeat"]) - {item["name"] for item in manifest}:
        raise SystemExit("repeat list contains an unknown repository")
    if cve_input["content_hash"] != cve["content_hash"]:
        raise SystemExit("CVE input and manifest hashes differ")
    if config["master"]["knowledge_cutoff"] > cve["fetched_at"]:
        raise SystemExit("knowledge cutoff must not be later than CVE snapshot")
    image_id = subprocess.run(
        ["docker", "image", "inspect", config["image"]["tag"], "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if image_id != config["image"]["id"]:
        raise SystemExit("Docker image changed after freeze; rebuild and regenerate run config")
    health = subprocess.run(
        ["curl", "-fsS", "http://127.0.0.1:8001/healthz"],
        check=True,
        capture_output=True,
        text=True,
    )
    print(
        json.dumps(
            {
                "repositories": len(manifest),
                "development": 100,
                "held_out": 200,
                "project_keys": len(keys),
                "cve_records": len(cve_input["records"]),
                "cve_missing": len(cve["missing"]),
                "image": image_id,
                "master": json.loads(health.stdout)["status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
