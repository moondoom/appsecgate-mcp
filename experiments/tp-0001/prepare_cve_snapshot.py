#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch a frozen OSV snapshot for report CVE/GHSA IDs")
    parser.add_argument(
        "--pattern",
        default="artifacts/agent300-preflight-gemmaq3-p1-*/report.json",
    )
    parser.add_argument("--prefix", default="agent300")
    return parser.parse_args()


def fetch(cve_id: str) -> dict | None:
    request = urllib.request.Request(
        f"https://api.osv.dev/v1/vulns/{cve_id}",
        headers={"Accept": "application/json", "User-Agent": "appsecgate-cve-snapshot"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return {
        "cve_id": cve_id,
        "summary": payload.get("summary"),
        "details": payload.get("details"),
        "aliases": payload.get("aliases", []),
        "published": payload.get("published"),
        "modified": payload.get("modified"),
        "severity": payload.get("severity", []),
        "cwe": payload.get("cwe", {}),
        "references": payload.get("references", []),
        "affected": payload.get("affected", []),
    }


def main() -> None:
    args = _args()
    ids: set[str] = set()
    for path in sorted(ROOT.glob(args.pattern)):
        text = path.read_text()
        if not text.strip():
            continue
        report = json.loads(text)
        if report.get("exit_reason") == "infrastructure_error":
            continue
        for finding in report.get("findings", []):
            rule = finding.get("rule_id") or ""
            if rule.startswith(("CVE-", "GHSA-")):
                ids.add(rule)
    records: dict[str, dict] = {}
    affected: dict[str, list[dict]] = {}
    missing: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, cve_id): cve_id for cve_id in sorted(ids)}
        for future in concurrent.futures.as_completed(futures):
            cve_id = futures[future]
            record = future.result()
            if record is None:
                missing.append(cve_id)
                continue
            records[cve_id] = record
            affected[cve_id] = [
                {
                    "ecosystem": item.get("package", {}).get("ecosystem", ""),
                    "package": item.get("package", {}).get("name", ""),
                    "ranges": item.get("ranges", []),
                }
                for item in record.pop("affected", [])
                if item.get("package", {}).get("name")
            ]
    fetched_at = datetime.now(timezone.utc).isoformat()
    content_hash = hashlib.sha256(
        json.dumps(
            {"records": records, "affected": affected, "missing": missing},
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    payload = {
        "source": "osv",
        "fetched_at": fetched_at,
        "content_hash": content_hash,
        "records": list(records.values()),
        "affected": affected,
    }
    (ROOT / "runtime").mkdir(exist_ok=True)
    (ROOT / "runtime" / "cve-input.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )
    manifest = {
        "source": "osv",
        "fetched_at": fetched_at,
        "content_hash": content_hash,
        "requested": sorted(ids),
        "imported": sorted(records),
        "missing": missing,
    }
    (ROOT / "artifacts" / f"{args.prefix}-cve-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps({"requested": len(ids), "imported": len(records), "missing": len(missing)}))


if __name__ == "__main__":
    main()
