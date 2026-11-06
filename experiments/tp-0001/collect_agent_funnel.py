#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HUMAN_FIELDS = ("human_verdict", "reviewer", "reviewed_at", "review_notes", "adjudication")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect autonomous-agent funnel and blind review rows")
    parser.add_argument("--label", required=True, help="Run label, for example asgfree300")
    parser.add_argument("--model", default="gemmaq3")
    parser.add_argument("--parallelism", type=int, default=4)
    parser.add_argument("--prefix", help="Artifact prefix; defaults to label")
    parser.add_argument("--pattern", help="Optional report glob relative to the experiment root")
    return parser.parse_args()


def _previous_reviews(path: Path) -> dict[tuple[str, str], dict]:
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text())
    return {(row["repo"], row["finding_id"]): row for row in rows}


def main() -> None:
    args = _args()
    prefix = args.prefix or args.label
    pattern = args.pattern or f"artifacts/{args.label}-{args.model}-p{args.parallelism}-*/report.json"
    report_paths = sorted(ROOT.glob(pattern))
    if not report_paths:
        raise SystemExit(f"no reports matched {pattern}")
    review_path = ROOT / "artifacts" / f"{prefix}-review.json"
    previous = _previous_reviews(review_path)
    funnel: list[dict] = []
    review: list[dict] = []
    skipped: list[dict] = []

    for report_path in report_paths:
        report = json.loads(report_path.read_text())
        run_id = report["run_id"]
        repo = run_id.removeprefix(f"{args.label}-{args.model}-")
        meta = report.get("scan_meta")
        if meta is None and report.get("exit_reason") == "infrastructure_error":
            skipped.append({"repo": repo, "reason": report.get("error", "infrastructure_error")})
            continue
        if meta is None:
            raise SystemExit(f"structured scan_meta is missing in {report_path}")
        inventory = report["inventory"]
        verdicts = {item["finding_id"]: item for item in report.get("verdicts", [])}
        model_counts = Counter(item["verdict"] for item in verdicts.values())
        row = {
            "repo": repo,
            "scanner_raw": meta["scanner_raw"],
            "in_scope": meta["in_scope"],
            "dedup_level1": meta["dedup_level1"],
            "dedup_level2": meta["dedup_level2"],
            "suppressed": meta["suppressed"],
            "eligible": meta["eligible"],
            "assigned": inventory["total"],
            "model_tp": model_counts["TRUE_POSITIVE"],
            "model_fp": model_counts["FALSE_POSITIVE"],
            "model_nr": model_counts["NEEDS_REVIEW"],
            "missing": len(inventory["missing_ids"]),
            "inventory_hash": inventory["hash"],
            "master_knowledge_unavailable": report.get("usage", {}).get(
                "master_knowledge_unavailable", 0
            ),
        }
        if row["assigned"] != row["eligible"]:
            raise SystemExit(f"eligible/assigned mismatch in {report_path}")
        if row["assigned"] != row["model_tp"] + row["model_fp"] + row["model_nr"] + row["missing"]:
            raise SystemExit(f"verdict coverage mismatch in {report_path}")
        funnel.append(row)

        for finding in report.get("findings", []):
            finding_id = finding["finding_id"]
            verdict = verdicts.get(finding_id)
            item = {
                "repo": repo,
                "finding_id": finding_id,
                "rule_id": finding.get("rule_id"),
                "file_path": finding.get("file_path"),
                "line_start": finding.get("line_start"),
                "severity": finding.get("severity"),
                "scanner": finding.get("scanner"),
                "category": finding.get("category"),
                "message": finding.get("message"),
                "metadata": finding.get("metadata", {}),
                "model_verdict": verdict["verdict"] if verdict else None,
                "model_explanation": verdict.get("explanation") if verdict else None,
                "model_evidence": verdict.get("evidence", []) if verdict else [],
                "inventory_hash": inventory["hash"],
            }
            old = previous.get((repo, finding_id), {})
            for field in HUMAN_FIELDS:
                item[field] = old.get(field)
            review.append(item)

    totals = {
        key: sum(row[key] for row in funnel)
        for key in (
            "scanner_raw",
            "in_scope",
            "dedup_level1",
            "dedup_level2",
            "suppressed",
            "eligible",
            "assigned",
            "model_tp",
            "model_fp",
            "model_nr",
            "missing",
        )
    }
    output = {
        "repos": funnel,
        "totals": {**totals, "repositories": len(funnel)},
        "skipped": skipped,
    }
    (ROOT / "artifacts" / f"{prefix}-funnel.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    )
    review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(output["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
