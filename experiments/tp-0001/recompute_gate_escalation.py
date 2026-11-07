#!/usr/bin/env python3
"""SEV-1 precondition tooling: offline gate recomputation with verdict-aware
severity escalation (open-tasks SEV-1, preconditions 2-3).

Replays existing run reports (no scanner, no DB, no migration) with an
effective-severity mapping applied to TRUE_POSITIVE verdicts only and
estimates the impact on gate_block share:

    python3 recompute_gate_escalation.py --mapping '{"secret":"critical"}'

Escalation itself stays disabled everywhere; this is measurement-only.
The replay approximates the CI severity gate (block_on, default
[critical, high]) without shown-state/POTENTIALLY_FIXED handling — recorded
as a limitation.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

_SEVERITIES = ("critical", "high", "medium", "low", "info")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mapping",
        default='{"secret": "critical"}',
        help="JSON category->escalated severity, applied to TRUE_POSITIVE only",
    )
    parser.add_argument("--block-on", default="critical,high")
    parser.add_argument(
        "--label", default="*", help="run_id glob under artifacts/ (e.g. 'accb' -> accb-*)"
    )
    args = parser.parse_args()
    mapping = {k.lower(): v.lower() for k, v in json.loads(args.mapping).items()}
    block_on = {s.strip().lower() for s in args.block_on.split(",")}
    pattern = args.label if "*" in args.label else f"{args.label}-*"

    runs: dict[str, Any] = {}
    totals = Counter()
    for report_path in sorted(ROOT.glob(f"artifacts/{pattern}/report.json")):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        run_id = report_path.parent.name
        verdicts = {
            v["finding_id"]: v["verdict"]
            for v in report.get("verdicts", [])
            if v.get("finding_id") and v.get("verdict")
        }
        current_blocked = set((report.get("GateSummary") or {}).get("blocked_fps") or [])
        newly_blocked: list[str] = []
        escalated: list[str] = []
        for finding in report.get("findings", []):
            fp = finding.get("fingerprint") or finding.get("finding_id")
            severity = (finding.get("severity") or "").lower()
            category = (finding.get("category") or "").lower()
            if verdicts.get(fp) != "TRUE_POSITIVE" or category not in mapping:
                continue
            target = mapping[category]
            if _SEVERITIES.index(target) < _SEVERITIES.index(severity):
                escalated.append(fp)
                # escalation is monotonic: it can only add blocks, so the
                # impact is current_blocked plus newly block-severity TPs
                if target in block_on and fp not in current_blocked:
                    newly_blocked.append(fp)
        runs[run_id] = {
            "current_blocked": len(current_blocked),
            "currently_failing": bool((report.get("GateSummary") or {}).get("should_fail")),
            "escalated_findings": len(escalated),
            "newly_blocked": sorted(newly_blocked),
            "would_flip_to_block": bool(newly_blocked)
            and not (report.get("GateSummary") or {}).get("should_fail"),
        }
        totals["current_blocked"] += len(current_blocked)
        totals["escalated_findings"] += len(escalated)
        totals["newly_blocked"] += len(newly_blocked)
        totals["would_flip_to_block"] += int(runs[run_id]["would_flip_to_block"])

    artifact = {
        "mapping": mapping,
        "block_on": sorted(block_on),
        "label": args.label,
        "runs": len(runs),
        "totals": dict(totals),
        "per_run": runs,
        "limitations": [
            "monotonic delta only: escalation never unblocks, so current blocked_fps is the baseline and only newly-blocked TPs are measured",
            "rule_classes filter unavailable: report.json has no rule class, mapping is per category",
            "duplicate runs of the same project (sweep arms) are counted per run",
        ],
    }
    output = ROOT / "artifacts" / "severity-escalation-impact.json"
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"runs": len(runs), "totals": dict(totals), "output": str(output)}))


if __name__ == "__main__":
    main()
