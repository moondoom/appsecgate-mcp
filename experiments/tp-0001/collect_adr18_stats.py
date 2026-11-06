#!/usr/bin/env python3
"""ADR-0018 Mode A categorical statistics for the agent300adr18 series."""
from __future__ import annotations

import json
import os
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LABEL = os.environ.get("STATS_LABEL", "agent300adr18")
BASELINE = os.environ.get("STATS_BASELINE", "agent300review")
LEVELS = ("high", "medium", "low", "speculative")
REASONS = ("ttl_expired", "legacy_confidence_missing", "prompt_updated")


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _events(run_id: str) -> list[dict[str, Any]]:
    path = ROOT / "runtime" / f"data-{run_id}" / "triage_verdicts.ndjson"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _project_key(name: str) -> str:
    return f"{name}-tp0001-agent300-gemmaq3-p1-{name}"


def _audit_outcomes(name: str, window_start: datetime | None) -> Counter[str]:
    config = _load(ROOT / "artifacts" / "agent300-run-config.json")
    keys = _load(ROOT / "runtime" / "agent300-keys.json")
    key = _project_key(name)
    url = f"{config['master']['host_url']}/v1/audit?project={key}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {keys[key]}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            rows = json.load(response).get("audit", [])
    except (OSError, ValueError):
        return Counter({"audit_unavailable": 1})
    outcomes: Counter[str] = Counter()
    for row in rows:
        if window_start is not None:
            try:
                received = datetime.fromisoformat(row["received_at"])
            except (KeyError, ValueError):
                continue
            if received < window_start:
                continue
        outcomes[row.get("outcome", "?")] += 1
    return outcomes


def _window_start(report: dict[str, Any]) -> datetime | None:
    try:
        generated = datetime.fromisoformat(report["generated_at"])
        return generated - timedelta(seconds=float(report.get("duration_sec", 0)))
    except (KeyError, ValueError, TypeError):
        return None


def _verdict_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["finding_id"]: item
        for item in report.get("verdicts", [])
        if isinstance(item, dict) and item.get("finding_id")
    }


def _mode_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    per_mode: dict[str, dict[str, Any]] = {}
    for event in events:
        mode = event.get("prompt_mode") or "unknown"
        bucket = per_mode.setdefault(
            mode,
            {
                "confidence_level": Counter(),
                "evidence_basis": Counter(),
                "model_confidence_level": Counter(),
                "verdicts": Counter(),
                "prompt_sha256": Counter(),
            },
        )
        bucket["confidence_level"][event.get("confidence_level") or "none"] += 1
        bucket["evidence_basis"][event.get("evidence_basis") or "none"] += 1
        bucket["model_confidence_level"][event.get("model_confidence_level") or "none"] += 1
        bucket["verdicts"][event.get("verdict") or "none"] += 1
        bucket["prompt_sha256"][event.get("prompt_sha256") or "none"] += 1
    return {
        mode: {
            key: (dict(sorted(value.items())) if isinstance(value, Counter) else value)
            for key, value in bucket.items()
        }
        for mode, bucket in sorted(per_mode.items())
    }


def collect() -> dict[str, Any]:
    config = _load(ROOT / "artifacts" / "agent300-run-config.json")
    names = config.get("repeat", [])
    rows = []
    transitions = []
    all_events: list[dict[str, Any]] = []
    for name in names:
        run_id = f"{LABEL}-gemmaq3-p1-{name}"
        report = _load(ROOT / "artifacts" / run_id / "report.json")
        usage = report.get("usage", {})
        verdicts = list(_verdict_map(report).values())
        events = _events(run_id)
        all_events.extend(events)
        counts = Counter(item.get("verdict") for item in verdicts)
        downgraded = [item for item in verdicts if item.get("downgrade_reason")]
        downgrade_reasons = Counter(item["downgrade_reason"] for item in downgraded)
        baseline = _load(ROOT / "artifacts" / f"{BASELINE}-gemmaq3-p1-{name}" / "report.json")
        current_by_id = _verdict_map(report)
        baseline_by_id = _verdict_map(baseline)
        common = current_by_id.keys() & baseline_by_id.keys()
        changed = [fp for fp in common if current_by_id[fp]["verdict"] != baseline_by_id[fp]["verdict"]]
        findings_by_id = {item.get("finding_id"): item for item in report.get("findings", [])}
        for fp in sorted(changed):
            transitions.append(
                {
                    "repository": name,
                    "finding_id": fp,
                    "rule_id": findings_by_id.get(fp, {}).get("rule_id"),
                    "before": baseline_by_id[fp]["verdict"],
                    "after": current_by_id[fp]["verdict"],
                    "before_confidence": baseline_by_id[fp].get("confidence"),
                    "after_confidence_level": current_by_id[fp].get("confidence_level"),
                    "explanation": current_by_id[fp].get("explanation"),
                }
            )
        raw = len(report.get("findings", []))
        unique_total = len({item.get("finding_id") for item in report.get("findings", [])})
        complete = (
            report.get("exit_reason") in {"report_generated", "gate_block"}
            and len(verdicts) == unique_total
            and usage.get("failed_findings", 0) == 0
        )
        audit = _audit_outcomes(name, _window_start(report))
        numeric_in_journal = sum("confidence" in event for event in events)
        rows.append(
            {
                "repository": name,
                "run_id": run_id,
                "status": report.get("exit_reason", "no_report"),
                "complete": complete,
                "findings_raw": raw,
                "unique_findings": unique_total,
                "coverage": f"{len(verdicts)}/{unique_total}",
                "verdicts": dict(sorted(counts.items())),
                "reuse_candidates": usage.get("reuse_candidates", 0),
                "reused": usage.get("reused_verdicts", 0),
                "reevaluated": usage.get("reevaluated_verdicts", 0),
                "revision_reasons": {
                    reason: usage.get(f"reevaluated_{reason}", 0) for reason in REASONS
                },
                "failed_findings": usage.get("failed_findings", 0),
                "missing": usage.get("missing", len(report.get("inventory", {}).get("missing_ids", []))),
                "evidence_reads": usage.get("evidence_reads", 0),
                "downgraded": len(downgraded),
                "downgrade_reasons": dict(sorted(downgrade_reasons.items())),
                "journal_events": len(events),
                "numeric_confidence_events": numeric_in_journal,
                "modes": _mode_stats(events),
                "ruleset_hashes": sorted({e.get("ruleset_hash") for e in events if e.get("ruleset_hash")}),
                "rule_hash_status": dict(Counter(e.get("rule_hash_status") for e in events)),
                "audit_outcomes": dict(sorted(audit.items())),
                "rejected_edge_validator": audit.get("rejected:edge_validator", 0),
                "warnings": report.get("warnings", []),
                "baseline_common": len(common),
                "verdict_drift": len(changed),
            }
        )
    aggregate_verdicts: Counter[str] = Counter()
    for row in rows:
        aggregate_verdicts.update(row["verdicts"])
    return {
        "label": LABEL,
        "baseline": BASELINE,
        "repositories": rows,
        "aggregate": {
            "runs": len(rows),
            "complete_runs": sum(row["complete"] for row in rows),
            "findings_raw": sum(row["findings_raw"] for row in rows),
            "unique_findings": sum(row["unique_findings"] for row in rows),
            "verdicts": dict(sorted(aggregate_verdicts.items())),
            "reuse_candidates": sum(row["reuse_candidates"] for row in rows),
            "reused": sum(row["reused"] for row in rows),
            "reevaluated": sum(row["reevaluated"] for row in rows),
            "revision_reasons": {
                reason: sum(row["revision_reasons"][reason] for row in rows) for reason in REASONS
            },
            "failed_findings": sum(row["failed_findings"] for row in rows),
            "missing": sum(row["missing"] for row in rows),
            "evidence_reads_zero": sum(row["evidence_reads"] == 0 for row in rows),
            "evidence_reads_nonzero": sum(row["evidence_reads"] > 0 for row in rows),
            "downgraded": sum(row["downgraded"] for row in rows),
            "journal_events": sum(row["journal_events"] for row in rows),
            "numeric_confidence_events": sum(row["numeric_confidence_events"] for row in rows),
            "rejected_edge_validator": sum(row["rejected_edge_validator"] for row in rows),
            "baseline_common": sum(row["baseline_common"] for row in rows),
            "verdict_drift": sum(row["verdict_drift"] for row in rows),
            "modes": _mode_stats(all_events),
        },
        "transitions": transitions,
    }


def main() -> None:
    result = collect()
    output = ROOT / "artifacts" / f"{LABEL}-stats.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **result["aggregate"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
