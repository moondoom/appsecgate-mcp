#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "artifacts" / "rev1-confidence-review.json"


def _rows():
    for path in sorted((ROOT / "artifacts").glob("agent300review-gemmaq3-p1-*/report.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        findings = {item["finding_id"]: item for item in report.get("findings", [])}
        for verdict in report.get("verdicts", []):
            confidence = verdict.get("confidence")
            if not isinstance(confidence, int):
                continue
            finding = findings.get(verdict["finding_id"], {})
            yield {
                "repo": path.parent.name.removeprefix("agent300review-gemmaq3-p1-"),
                "finding_id": verdict["finding_id"],
                "rule_id": finding.get("rule_id"),
                "file_path": finding.get("file_path"),
                "line_start": finding.get("line_start"),
                "scanner": finding.get("scanner"),
                "model_verdict": verdict["verdict"],
                "confidence": confidence,
                "model_explanation": verdict.get("explanation"),
                "human_verdict": None,
                "reviewer": None,
                "reviewed_at": None,
                "review_notes": None,
            }


def main() -> None:
    rows = list(_rows())
    low = sorted((row for row in rows if row["confidence"] < 50), key=lambda row: row["finding_id"])
    medium = sorted(
        (row for row in rows if 50 <= row["confidence"] < 80),
        key=lambda row: row["finding_id"],
    )
    high_groups = defaultdict(list)
    for row in rows:
        if row["confidence"] >= 80:
            high_groups[(row["scanner"], row["model_verdict"])].append(row)
    for group in high_groups.values():
        group.sort(key=lambda row: row["finding_id"])
    high = []
    remaining = max(0, 100 - len(low) - len(medium))
    while len(high) < remaining and any(high_groups.values()):
        for key in sorted(high_groups):
            if high_groups[key] and len(high) < remaining:
                high.append(high_groups[key].pop(0))
    selected = sorted(
        [*low, *medium, *high], key=lambda row: (row["repo"], row["finding_id"])
    )
    OUTPUT.write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "total": len(selected),
        "low": len(low),
        "medium": len(medium),
        "high": len(high),
    }))


if __name__ == "__main__":
    main()
