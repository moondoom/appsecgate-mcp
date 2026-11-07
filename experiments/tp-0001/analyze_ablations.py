#!/usr/bin/env python3
"""A1/A2 same-session ablation analysis (consolidated review 2026-11-07).

A2: artifacts/sort-ablation-same-session.json — asa-d (mode_major) vs asa-d2 (none).
A1: artifacts/read-project-file-ablation.json — arf-on (MODE_B=1) vs arf-off (MODE_B=0).

Both cells of a pair must share inventory_hash and prompt_sha256, otherwise the
ablation is invalid and no gate verdict is emitted.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"


def load_cell(label: str) -> dict:
    run_dir = ARTIFACTS / f"{label}-gemmaq3-p1-atopile"
    report = json.loads((run_dir / "report.json").read_text())
    usage = report.get("usage", {})
    verdicts = report.get("verdicts", [])
    judged = [v for v in verdicts if v.get("verdict")]
    nr = [v for v in judged if v["verdict"] == "NEEDS_REVIEW"]
    tool_counts = Counter(a.get("tool") for a in report.get("action_log", []))
    return {
        "run_id": report["run_id"],
        "duration_sec": report.get("duration_sec"),
        "inventory_hash": (report.get("inventory") or {}).get("hash"),
        "findings_total": (report.get("inventory") or {}).get("total"),
        "prompt_sha256": report.get("prompt_sha256"),
        "verdict_counts": dict(Counter(v["verdict"] for v in judged)),
        "nr_rate": len(nr) / len(judged) if judged else None,
        "failure_reasons": dict(
            Counter(v["failure_reason"] for v in verdicts if v.get("failure_reason"))
        ),
        "tokens_per_finding": (
            usage.get("total_tokens") / len(judged) if judged and usage.get("total_tokens") else None
        ),
        "total_tokens": usage.get("total_tokens"),
        "batch_retries": usage.get("batch_retries"),
        "read_project_file_calls": tool_counts.get("read_project_file", 0),
        "tool_calls": usage.get("tool_calls"),
        "verdicts_by_finding": {v["finding_id"]: v["verdict"] for v in judged},
    }


def verdict_parity(a: dict, b: dict) -> dict:
    common = set(a["verdicts_by_finding"]) & set(b["verdicts_by_finding"])
    drift = sum(
        1 for fp in common if a["verdicts_by_finding"][fp] != b["verdicts_by_finding"][fp]
    )
    return {
        "common_findings": len(common),
        "drifted": drift,
        "drift_rate": drift / len(common) if common else None,
    }


def validate_pair(a: dict, b: dict) -> list[str]:
    problems = []
    if a["inventory_hash"] != b["inventory_hash"]:
        problems.append(f"inventory_hash mismatch: {a['inventory_hash']} vs {b['inventory_hash']}")
    if a["prompt_sha256"] != b["prompt_sha256"]:
        problems.append("prompt_sha256 mismatch")
    return problems


def strip(cell: dict) -> dict:
    return {k: v for k, v in cell.items() if k != "verdicts_by_finding"}


def main() -> None:
    d = load_cell("asa-d")
    d2 = load_cell("asa-d2")
    on = load_cell("arf-on")
    off = load_cell("arf-off")

    # --- A2: sorting ---
    sort_problems = validate_pair(d, d2)
    delta_wall = (
        (d["duration_sec"] - d2["duration_sec"]) / d2["duration_sec"]
        if d2["duration_sec"]
        else None
    )
    if sort_problems:
        sort_gate = "invalid"
    elif delta_wall is not None and delta_wall > 0.15:
        sort_gate = "remove_sorting"
    elif delta_wall is not None and delta_wall < 0.10:
        sort_gate = "confound_confirmed_keep_mode_major"
    else:
        sort_gate = "indeterminate_repeat_once"
    sort_out = {
        "experiment": "A2 sort ablation, same session, atopile",
        "cells": {"mode_major": strip(d), "none": strip(d2)},
        "validity_problems": sort_problems,
        "delta_wall_rel_to_none": delta_wall,
        "verdict_parity": verdict_parity(d, d2),
        "gate": sort_gate,
    }
    (ARTIFACTS / "sort-ablation-same-session.json").write_text(json.dumps(sort_out, indent=2) + "\n")

    # --- A1: read_project_file ---
    rf_problems = validate_pair(on, off)
    delta_nr_pp = (
        (off["nr_rate"] - on["nr_rate"]) * 100
        if off["nr_rate"] is not None and on["nr_rate"] is not None
        else None
    )
    if rf_problems:
        rf_gate = "invalid"
    elif delta_nr_pp is not None and delta_nr_pp > 10:
        rf_gate = "revert_removal_restore_under_dedicated_flag"
    elif delta_nr_pp is not None and delta_nr_pp > 5:
        rf_gate = "confirmed_with_note_used_but_not_decisive"
    else:
        rf_gate = "removal_confirmed"
    rf_out = {
        "experiment": "A1 read_project_file NR ablation, same session, atopile",
        "cells": {"mode_b_on": strip(on), "mode_b_off": strip(off)},
        "validity_problems": rf_problems,
        "delta_nr_pp_off_minus_on": delta_nr_pp,
        "verdict_parity": verdict_parity(on, off),
        "gate": rf_gate,
    }
    (ARTIFACTS / "read-project-file-ablation.json").write_text(json.dumps(rf_out, indent=2) + "\n")

    print(json.dumps({"sort_gate": sort_gate, "rf_gate": rf_gate,
                      "delta_wall": delta_wall, "delta_nr_pp": delta_nr_pp}, indent=2))


if __name__ == "__main__":
    main()
