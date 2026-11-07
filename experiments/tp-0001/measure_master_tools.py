#!/usr/bin/env python3
"""GD-13: master-tool usage measurement for guided runs (ADR-0019 Part 7).

Counts tool invocations per run label from agent.log lines (`tool=<name>`)
and summarizes verdict evidence_basis as a dependency proxy. Output:
artifacts/master-tools-usage.json. Removal of master tools from guided is
allowed only when usage is ~0 and no verdict depends on those calls.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LABELS = ["agent300fix1", "agent300adr18", "agent300review", "accb", "accb2", "accd", "acce"]
TOOL_RE = re.compile(r"tool=([a-z_]+)")
MASTER_TOOLS = {"master_describe_schema", "master_query_findings_db"}


def main() -> None:
    report: dict[str, object] = {}
    totals: Counter = Counter()
    for label in LABELS:
        per_run = {}
        for log in sorted(ROOT.glob(f"artifacts/{label}-*/agent.log")):
            counts = Counter(TOOL_RE.findall(log.read_text(encoding="utf-8", errors="replace")))
            if not counts:
                continue
            run_id = log.parent.name
            per_tool = dict(counts)
            master_calls = sum(counts[t] for t in MASTER_TOOLS)
            totals.update(counts)
            verdicts_path = ROOT / "runtime" / f"data-{run_id}" / "triage_verdicts.ndjson"
            basis: Counter = Counter()
            if verdicts_path.exists():
                for line in verdicts_path.read_text().splitlines():
                    try:
                        basis[json.loads(line).get("evidence_basis") or "none"] += 1
                    except json.JSONDecodeError:
                        continue
            per_tool_report = {k: v for k, v in sorted(counts.items(), key=lambda kv: -kv[1])}
            report[run_id] = {
                "tools": per_tool_report,
                "master_calls": master_calls,
                "evidence_basis": dict(basis),
            }
    master_total = sum(totals[t] for t in MASTER_TOOLS)
    summary = {
        "labels": LABELS,
        "runs": len(report),
        "tool_totals": dict(totals.most_common()),
        "master_calls_total": master_total,
        "verdict_dependency": "none measurable: no master calls in any run"
        if master_total == 0
        else "manual review required",
        "recommendation": (
            "remove master_describe_schema/master_query_findings_db from the guided tool list; "
            "keep read_project_file gated by APPSECGATE_MODE_B (usage is file reads, not master)"
            if master_total == 0
            else "usage is material; deterministic pre-fetch (Part 6) is mandatory before removal"
        ),
        "runs_detail": report,
    }
    output = ROOT / "artifacts" / "master-tools-usage.json"
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"runs": len(report), "master_calls_total": master_total}))


if __name__ == "__main__":
    main()
