#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LABEL = "agent300review"
BASELINE = "agent300"


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _confidence_stats(verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        item["confidence"]
        for item in verdicts
        if isinstance(item.get("confidence"), int) and not isinstance(item["confidence"], bool)
    ]
    bands = Counter()
    for value in values:
        if value < 50:
            bands["0-49"] += 1
        elif value < 80:
            bands["50-79"] += 1
        elif value <= 100:
            bands["80-100"] += 1
    return {
        "known": len(values),
        "missing": len(verdicts) - len(values),
        "bands": dict(sorted(bands.items())),
        "mean": round(statistics.mean(values), 2) if values else None,
        "median": statistics.median(values) if values else None,
    }


def _journal_stats(run_id: str) -> dict[str, int]:
    path = ROOT / "runtime" / f"data-{run_id}" / "triage_verdicts.ndjson"
    try:
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return {"events": 0, "complete_provenance": 0, "superseded": 0}
    required = ("actor_id", "model", "prompt_sha256", "ruleset_hash", "rule_hash_status")
    return {
        "events": len(events),
        "complete_provenance": sum(all(event.get(key) for key in required) for event in events),
        "superseded": sum(bool(event.get("supersedes_verdict_id")) for event in events),
    }


def _verdict_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["finding_id"]: item
        for item in report.get("verdicts", [])
        if isinstance(item, dict) and item.get("finding_id")
    }


def collect() -> dict[str, Any]:
    config = _load(ROOT / "artifacts" / "agent300-run-config.json")
    names = config.get("repeat", [])
    rows = []
    transitions = []
    all_verdicts = []
    for name in names:
        run_id = f"{LABEL}-gemmaq3-p1-{name}"
        report = _load(ROOT / "artifacts" / run_id / "report.json")
        usage = report.get("usage", {})
        verdicts = list(_verdict_map(report).values())
        all_verdicts.extend(verdicts)
        counts = Counter(item.get("verdict") for item in verdicts)
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
                    "after_confidence": current_by_id[fp].get("confidence"),
                    "explanation": current_by_id[fp].get("explanation"),
                }
            )
        total = report.get("inventory", {}).get("total", 0)
        unique_total = len({item.get("finding_id") for item in report.get("findings", [])})
        complete = (
            report.get("exit_reason") in {"report_generated", "gate_block"}
            and len(verdicts) == unique_total
            and usage.get("failed_findings", 0) == 0
        )
        rows.append(
            {
                "repository": name,
                "run_id": run_id,
                "status": report.get("exit_reason", "no_report"),
                "complete": complete,
                "findings": total,
                "unique_findings": unique_total,
                "verdicts": dict(sorted(counts.items())),
                "reused": usage.get("reused_verdicts", 0),
                "reevaluated": usage.get("reevaluated_verdicts", 0),
                "reevaluated_ttl_expired": usage.get("reevaluated_ttl_expired", 0),
                "reevaluated_legacy": usage.get("reevaluated_legacy_confidence_missing", 0),
                "failed_findings": usage.get("failed_findings", 0),
                "missing": usage.get("missing", len(report.get("inventory", {}).get("missing_ids", []))),
                "confidence": _confidence_stats(verdicts),
                "baseline_common": len(common),
                "verdict_drift": len(changed),
                "journal": _journal_stats(run_id),
            }
        )
    aggregate_counts = Counter(item.get("verdict") for item in all_verdicts)
    return {
        "label": LABEL,
        "baseline": BASELINE,
        "repositories": rows,
        "aggregate": {
            "runs": len(rows),
            "complete_runs": sum(row["complete"] for row in rows),
            "findings": sum(row["findings"] for row in rows),
            "unique_findings": sum(row["unique_findings"] for row in rows),
            "verdicts": dict(sorted(aggregate_counts.items())),
            "reused": sum(row["reused"] for row in rows),
            "reevaluated": sum(row["reevaluated"] for row in rows),
            "reevaluated_ttl_expired": sum(row["reevaluated_ttl_expired"] for row in rows),
            "reevaluated_legacy": sum(row["reevaluated_legacy"] for row in rows),
            "failed_findings": sum(row["failed_findings"] for row in rows),
            "missing": sum(row["missing"] for row in rows),
            "confidence": _confidence_stats(all_verdicts),
            "baseline_common": sum(row["baseline_common"] for row in rows),
            "verdict_drift": sum(row["verdict_drift"] for row in rows),
            "journal_events": sum(row["journal"]["events"] for row in rows),
            "complete_provenance": sum(row["journal"]["complete_provenance"] for row in rows),
            "superseded_events": sum(row["journal"]["superseded"] for row in rows),
        },
        "transitions": transitions,
    }


def main() -> None:
    result = collect()
    output = ROOT / "artifacts" / f"{LABEL}-reevaluation-stats.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **result["aggregate"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
