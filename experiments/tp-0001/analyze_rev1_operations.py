#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "artifacts" / "rev1-operations.json"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _events(run_id: str) -> list[dict[str, Any]]:
    path = ROOT / "runtime" / f"data-{run_id}" / "triage_verdicts.ndjson"
    return [_load_line(line) for line in path.read_text().splitlines() if line.strip()]


def _load_line(line: str) -> dict[str, Any]:
    return json.loads(line)


def _bitcore() -> dict[str, Any]:
    run_id = "agent300review-gemmaq3-p1-bitcore"
    events = _events(run_id)
    timestamps = sorted(datetime.fromisoformat(event["at"]) for event in events)
    gaps = [(later - earlier).total_seconds() for earlier, later in zip(timestamps, timestamps[1:])]
    duration = (timestamps[-1] - timestamps[0]).total_seconds()
    per_minute = Counter(item.strftime("%H:%M") for item in timestamps)
    log = (ROOT / "artifacts" / run_id / "agent.log").read_text(encoding="utf-8")
    raw_match = re.search(r"scan done mode=project findings=(\d+)", log)
    raw_inventory = int(raw_match.group(1)) if raw_match else None
    return {
        "raw_inventory": raw_inventory,
        "events": len(events),
        "unique_verdict_ids": len({event["fp"] for event in events}),
        "raw_coverage_percent": round(100 * len(events) / raw_inventory, 2),
        "first_event": timestamps[0].isoformat(),
        "last_event": timestamps[-1].isoformat(),
        "duration_seconds": round(duration, 3),
        "events_per_minute": round(len(events) * 60 / duration, 2),
        "max_event_gap_seconds": max(gaps, default=0),
        "events_by_minute": dict(sorted(per_minute.items())),
        "scanners": dict(Counter(event.get("scanner") for event in events)),
        "verdicts": dict(Counter(event.get("verdict") for event in events)),
        "log_signals": {
            "loop": len(re.findall(r"\bloop", log, re.IGNORECASE)),
            "restart": len(re.findall(r"\brestart", log, re.IGNORECASE)),
            "token_repeat": len(re.findall(r"token repeat", log, re.IGNORECASE)),
        },
        "assessment": (
            "continuous progress consistent with sizing/timeout; no loop evidence"
            if max(gaps, default=0) < 120 and not re.search(r"\bloop|token repeat", log, re.I)
            else "requires manual loop/stall review"
        ),
    }


def _aiwritex() -> dict[str, Any]:
    report = _load(ROOT / "artifacts" / "agent300review-gemmaq3-p1-AIWriteX" / "report.json")
    missing_ids = report.get("inventory", {}).get("missing_ids", [])
    findings = {item["finding_id"]: item for item in report.get("findings", [])}
    return {
        "missing_ids": missing_ids,
        "missing_findings": [
            {
                "finding_id": finding_id,
                "scanner": findings.get(finding_id, {}).get("scanner"),
                "rule_id": findings.get(finding_id, {}).get("rule_id"),
                "file_path": findings.get(finding_id, {}).get("file_path"),
                "line_start": findings.get(finding_id, {}).get("line_start"),
            }
            for finding_id in missing_ids
        ],
        "usage": {
            key: report.get("usage", {}).get(key)
            for key in (
                "failed_findings",
                "missing",
                "batch_retries",
                "evidence_reads",
                "total_tokens",
                "guided_incomplete",
            )
        },
        "tool_errors": [
            item for item in report.get("action_log", []) if item.get("status") not in {None, "ok"}
        ],
    }


def _normalize_snippet(snippet: str) -> str:
    text = re.sub(r"\s*(?://|#|/\*|<!--|--).*$", "", snippet.strip(), flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip().lower()


def _duplicates() -> dict[str, Any]:
    groups = []
    for path in sorted((ROOT / "artifacts").glob("agent300review-gemmaq3-p1-*/report.json")):
        report = _load(path)
        by_id: dict[str, list[dict[str, Any]]] = {}
        for finding in report.get("findings", []):
            by_id.setdefault(finding["finding_id"], []).append(finding)
        for finding_id, items in by_id.items():
            if len(items) < 2:
                continue
            scanners = {item.get("scanner") for item in items}
            rules = {item.get("rule_id") for item in items}
            snippets = {_normalize_snippet(item.get("snippet", "")) for item in items}
            if len(scanners) > 1:
                kind = "cross_scanner"
            elif len(rules) == 1 and len(snippets) == 1:
                kind = "same_rule_and_snippet_different_location"
            else:
                kind = "same_scanner_variant"
            groups.append(
                {
                    "repository": path.parent.name.removeprefix("agent300review-gemmaq3-p1-"),
                    "finding_id": finding_id,
                    "kind": kind,
                    "rows": len(items),
                    "scanner": sorted(scanners),
                    "rule_id": sorted(rules),
                    "file_path": sorted({item.get("file_path") for item in items}),
                    "lines": sorted({item.get("line_start") for item in items}),
                }
            )
    return {
        "duplicate_rows": sum(item["rows"] - 1 for item in groups),
        "groups": len(groups),
        "by_kind": dict(Counter(item["kind"] for item in groups)),
        "items": groups,
    }


def main() -> None:
    result = {
        "bitcore": _bitcore(),
        "aiwritex": _aiwritex(),
        "duplicates": _duplicates(),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "bitcore": {key: result["bitcore"][key] for key in (
            "raw_inventory", "events", "raw_coverage_percent", "events_per_minute",
            "max_event_gap_seconds", "log_signals", "assessment"
        )},
        "aiwritex": result["aiwritex"],
        "duplicates": {key: result["duplicates"][key] for key in (
            "duplicate_rows", "groups", "by_kind"
        )},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
