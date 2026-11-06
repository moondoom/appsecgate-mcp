#!/usr/bin/env python3
"""Stratified blind review bundle for the ADR-0018 Mode A (agent300adr18) series.

Produces two artifacts:
- adr18-confidence-review.json — human labeling sheet WITHOUT model answers
  (verdict / confidence_level / evidence_basis are assigned blind);
- adr18-confidence-review-model.json — model answers keyed by finding_id,
  revealed only after labeling.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LABEL = "agent300adr18"
OUTPUT_BLIND = ROOT / "artifacts" / "adr18-confidence-review.json"
OUTPUT_MODEL = ROOT / "artifacts" / "adr18-confidence-review-model.json"
TARGET = 100


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _rows():
    for path in sorted((ROOT / "artifacts").glob(f"{LABEL}-gemmaq3-p1-*/report.json")):
        report = _load(path)
        if not report:
            continue
        repo = path.parent.name.removeprefix(f"{LABEL}-gemmaq3-p1-")
        evidence_reads = report.get("usage", {}).get("evidence_reads", 0)
        findings = {item["finding_id"]: item for item in report.get("findings", [])}
        events = {}
        journal = ROOT / "runtime" / f"data-{path.parent.name}" / "triage_verdicts.ndjson"
        if journal.exists():
            for line in journal.read_text().splitlines():
                if line.strip():
                    event = json.loads(line)
                    events[event.get("fp")] = event
        for verdict in report.get("verdicts", []):
            finding = findings.get(verdict["finding_id"], {})
            event = events.get(verdict["finding_id"], {})
            mode = event.get("prompt_mode") or "sast"
            yield {
                "repo": repo,
                "finding_id": verdict["finding_id"],
                "scanner": finding.get("scanner"),
                "category": finding.get("category"),
                "mode": mode,
                "rule_id": finding.get("rule_id"),
                "file_path": finding.get("file_path"),
                "line_start": finding.get("line_start"),
                "severity": finding.get("severity"),
                "snippet": finding.get("snippet"),
                "evidence_reads": evidence_reads,
                "model": {
                    "verdict": verdict.get("verdict"),
                    "confidence_level": verdict.get("confidence_level"),
                    "evidence_basis": verdict.get("evidence_basis"),
                    "model_confidence_level": verdict.get("model_confidence_level"),
                    "model_verdict": verdict.get("model_verdict"),
                    "downgrade_reason": verdict.get("downgrade_reason"),
                    "evidence_quote": verdict.get("evidence_quote"),
                    "reasoning": verdict.get("reasoning"),
                },
            }


def main() -> None:
    rows = list(_rows())
    low_spec = sorted(
        (row for row in rows if row["model"]["confidence_level"] in {"low", "speculative"}),
        key=lambda row: (row["repo"], row["finding_id"]),
    )
    downgraded_groups = defaultdict(list)
    for row in rows:
        if row["model"]["downgrade_reason"] and row["model"]["confidence_level"] not in {
            "low",
            "speculative",
        }:
            downgraded_groups[(row["mode"], row["model"]["downgrade_reason"])].append(row)
    for group in downgraded_groups.values():
        group.sort(key=lambda row: (row["repo"], row["finding_id"]))
    downgraded: list = []
    downgraded_budget = min(len(low_spec), TARGET // 2)
    while len(downgraded) < downgraded_budget and any(downgraded_groups.values()):
        for key in sorted(downgraded_groups):
            if downgraded_groups[key] and len(downgraded) < downgraded_budget:
                downgraded.append(downgraded_groups[key].pop(0))
    mandatory = sorted(
        [*low_spec, *downgraded], key=lambda row: (row["repo"], row["finding_id"])
    )
    selected = list(mandatory)
    groups = defaultdict(list)
    selected_keys = {(row["repo"], row["finding_id"]) for row in selected}
    for row in rows:
        if (row["repo"], row["finding_id"]) in selected_keys:
            continue
        groups[(row["mode"], row["model"]["confidence_level"])].append(row)
    for group in groups.values():
        group.sort(key=lambda row: (row["repo"], row["finding_id"]))
    remaining = max(0, TARGET - len(selected))
    while remaining and any(groups.values()):
        for key in sorted(groups):
            if groups[key] and remaining:
                selected.append(groups[key].pop(0))
                remaining -= 1
    selected.sort(key=lambda row: (row["repo"], row["finding_id"]))

    blind = []
    model_answers = {}
    for row in selected:
        blind.append(
            {
                "repo": row["repo"],
                "finding_id": row["finding_id"],
                "scanner": row["scanner"],
                "category": row["category"],
                "mode": row["mode"],
                "rule_id": row["rule_id"],
                "file_path": row["file_path"],
                "line_start": row["line_start"],
                "severity": row["severity"],
                "snippet": row["snippet"],
                "human_verdict": None,
                "human_confidence_level": None,
                "human_evidence_basis": None,
                "reviewer": None,
                "reviewed_at": None,
                "review_notes": None,
            }
        )
        model_answers[f"{row['repo']}:{row['finding_id']}"] = row["model"]
    OUTPUT_BLIND.write_text(json.dumps(blind, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_MODEL.write_text(
        json.dumps(model_answers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "blind": str(OUTPUT_BLIND),
                "model": str(OUTPUT_MODEL),
                "total": len(blind),
                "mandatory_low_speculative_downgraded": len(mandatory),
            }
        )
    )


if __name__ == "__main__":
    main()
