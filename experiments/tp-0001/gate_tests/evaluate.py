#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(run: str) -> tuple[dict, int]:
    artifact = ROOT / "artifacts" / run
    return json.loads((artifact / "report.json").read_text()), int(
        (artifact / "exit_code").read_text()
    )


PREFIX = __import__("os").environ.get("GATE_PREFIX", "gate01fix1")


def evaluate(model: str) -> dict[str, bool]:
    results: dict[str, bool] = {}
    report, exit_code = load(f"{PREFIX}-{model}-t01b")
    results["T-01"] = (
        exit_code == 0
        and report["GateSummary"]["should_fail"]
        and report["GateSummary"]["by_reason"].get("unresolved_local", 0) > 0
    )
    for test, expectation in (("t02", "T-02"), ("t06", "T-06")):
        report, exit_code = load(f"{PREFIX}-{model}-{test}b")
        results[expectation] = (
            exit_code == 0 and not report["GateSummary"]["should_fail"] and not report["findings"]
        )
    before, _ = load(f"{PREFIX}-{model}-t03a")
    report, exit_code = load(f"{PREFIX}-{model}-t03b")
    original_ids = {item["finding_id"] for item in before["findings"]}
    remaining_ids = {item["finding_id"] for item in report["findings"]}
    results["T-03"] = (
        exit_code == 0
        and not report["GateSummary"]["should_fail"]
        and "adbf838f55ba7600" in original_ids - remaining_ids
    )
    report, exit_code = load(f"{PREFIX}-{model}-t04")
    results["T-04"] = exit_code == 2 and report["exit_reason"] == "infrastructure_error"
    report, exit_code = load(f"{PREFIX}-{model}-t05b")
    results["T-05"] = exit_code == 0 and not report["GateSummary"]["should_fail"]
    first, first_exit = load(f"{PREFIX}-{model}-t07")
    second, second_exit = load(f"{PREFIX}-{model}-t07")
    results["T-07"] = (
        first_exit == second_exit == 0 and first["run_id"] == second["run_id"]
    )
    report, exit_code = load(f"{PREFIX}-{model}-t08")
    results["T-08"] = exit_code == 0 and report["GateSummary"]["should_fail"]
    return results


def main() -> None:
    import os
    import sys

    models = sys.argv[1:] or ["qwen", "glm", "gemma4"]
    results = {model: evaluate(model) for model in models}
    path = ROOT / "artifacts" / f"{os.environ.get('GATE_PREFIX', 'gate01fix1')}-gate-results.json"
    path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
