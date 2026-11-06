#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAMESPACE = uuid.UUID("a55d96f2-07ca-4b7f-9c1f-f53af59e06c4")
PROJECT = "agent-dev-knowledge"
API_KEY = "agent-dev-knowledge-key"


def _utc(value: str | None) -> str:
    if not value:
        return "2026-11-03T00:00:00Z"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def main() -> None:
    rows = json.loads((ROOT / "artifacts" / "vibe100-triage.json").read_text())
    master_url = os.environ.get("APPSECGATE_MASTER_HOST_URL", "http://127.0.0.1:8001")
    events = []
    for row in rows:
        if row.get("triage_verdict") not in {"TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"}:
            continue
        key = f"{row['repo']}:{row['rule']}:{row['file']}:{row['line']}:{row['scanner']}"
        verdict_id = str(uuid.uuid5(NAMESPACE, key))
        created_at = _utc(row.get("last_commit_at"))
        rule = row["rule"]
        event = {
            "schema_version": 1,
            "client_event_id": verdict_id,
            "project_key": PROJECT,
            "event_type": "triage_verdicted",
            "at": created_at,
            "fp": uuid.uuid5(NAMESPACE, f"fp:{key}").hex,
            "verdict_id": verdict_id,
            "run_id": "vibe100-human-review",
            "verdict": row["triage_verdict"],
            "verdict_source": "human",
            "review_status": "confirmed",
            "rule_id": rule,
            "explanation": row.get("triage_reason") or "human reviewed",
            "evidence": [{"kind": "scanner", "scanner": row["scanner"]}],
            "agent_version": "human-review-v1",
            "cve_id": rule if rule.startswith(("CVE-", "GHSA-")) else None,
            "created_at": created_at,
        }
        events.append(event)

    outcomes = []
    for offset in range(0, len(events), 200):
        batch = events[offset : offset + 200]
        request = urllib.request.Request(
            f"{master_url}/v1/events",
            data=json.dumps({"events": batch}, ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                outcomes.extend(json.load(response)["outcomes"])
        except urllib.error.HTTPError as exc:
            outcomes.extend(json.load(exc).get("outcomes", []))
    summary = {}
    for outcome in outcomes:
        summary[outcome["outcome"]] = summary.get(outcome["outcome"], 0) + 1
    print(json.dumps({"events": len(events), "outcomes": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
