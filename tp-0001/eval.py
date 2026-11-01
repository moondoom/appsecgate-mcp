#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--ground-truth", default="repos/stage1_project.json")
    parser.add_argument("--master-checks")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = load(args.report)
    truth = load(args.ground_truth)
    if truth.get("ground_truth_status") != "approved":
        raise SystemExit("ground truth is not approved")

    expected = {item["finding_id"]: item["verdict"] for item in truth["ground_truth"]}
    actual = {item["finding_id"]: item["verdict"] for item in report["verdicts"]}
    tp = fp = fn = 0
    for finding_id, label in expected.items():
        predicted = actual.get(finding_id)
        if label == "FALSE_POSITIVE" and predicted == "FALSE_POSITIVE":
            tp += 1
        elif label == "FALSE_POSITIVE":
            fn += 1
        elif predicted == "FALSE_POSITIVE":
            fp += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    master = load(args.master_checks) if args.master_checks else {}
    master_applicable = [master.get(f"D{i}") for i in range(1, 8)]
    master_applicable = [item for item in master_applicable if item is not None]
    result = {
        "run_id": report["run_id"],
        "model": report["model"],
        "exit_reason": report["exit_reason"],
        "gate_block": report["GateSummary"]["should_fail"],
        "fp_precision": precision,
        "fp_recall": recall,
        "fp_f1": f1,
        "verdicts": dict(Counter(item["verdict"] for item in report["verdicts"])),
        "usage": report["usage"],
        "duration_sec": report["duration_sec"],
        "master_score": sum(master_applicable) / len(master_applicable) if master_applicable else None,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
