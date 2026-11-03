#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path


def get_json(url: str, api_key: str) -> list[dict]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if isinstance(payload, list):
        return payload
    return payload.get("items") or payload.get("findings") or payload.get("audit") or []


def timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edge-db", required=True)
    parser.add_argument("--master-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--agent-exit", type=int)
    parser.add_argument("--output")
    args = parser.parse_args()

    db = sqlite3.connect(f"file:{Path(args.edge_db)}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT fingerprint, last_shown_at FROM shown_findings WHERE project_id=?",
        (args.project_id,),
    ).fetchall()
    edge = {row["fingerprint"]: row["last_shown_at"] for row in rows}
    url = f"{args.master_url.rstrip('/')}/v1/findings?project={args.project_id}"
    master_rows = get_json(url, args.api_key)
    audit_url = f"{args.master_url.rstrip('/')}/v1/audit?project={args.project_id}"
    audit_rows = get_json(audit_url, args.api_key)
    received_by_fp: dict[str, datetime] = {}
    for item in audit_rows:
        fingerprint = item.get("fp")
        received = timestamp(item.get("received_at"))
        if fingerprint and received:
            current = received_by_fp.get(fingerprint)
            if current is None or received < current:
                received_by_fp[fingerprint] = received
    fingerprints = [item.get("fingerprint") or item["fp"] for item in master_rows]
    master = set(fingerprints)
    edge_set = set(edge)

    delays = []
    for item in master_rows:
        fingerprint = item.get("fingerprint") or item["fp"]
        shown = timestamp(edge.get(fingerprint))
        received = timestamp(item.get("master_received_at") or item.get("created_at"))
        received = received or received_by_fp.get(fingerprint)
        if shown and received:
            delays.append(max(0.0, (received - shown).total_seconds()))
    delays.sort()
    p95 = delays[min(len(delays) - 1, int(len(delays) * 0.95))] if delays else None
    duplicates = sum(count - 1 for count in Counter(fingerprints).values())
    result = {
        "D1": float(bool(edge_set) and edge_set == master),
        "D2": p95 is not None and p95 < 300,
        "D2_p95_sec": p95,
        "D3": float(duplicates == 0),
        "D4": float(bool(edge_set) and edge_set == master),
        "D5": None,
        "D6": None,
        "D7": None,
        "D8": float(args.agent_exit == 2) if args.agent_exit is not None else None,
        "edge_count": len(edge_set),
        "master_count": len(master_rows),
        "duplicates": duplicates,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
