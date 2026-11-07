#!/usr/bin/env python3
"""Funnel x token-cost report for a run series (corpus 300 readiness).

Joins per-call telemetry (llm_calls.ndjson) with the verdict journal
(triage_verdicts.ndjson) and the run report for every run of a label and
produces artifacts/funnel-cost-{label}.json:

- funnel stages: eligible -> verdicted (TP/FP/NR judged / NR model-failed by
  reason) -> high-confidence share;
- token cost per stage per mode: prompt/completion tokens from provider usage
  (null when the provider did not report), call count, evidence reads;
- lever table: which config knob shifts which funnel transition and at what
  token price direction (recorded, not computed).

Token attribution per finding is approximate: call tokens are divided equally
across the call's chunk (batches are mode-homogeneous under mode_major).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

LEVERS = {
    "reuse_verdicts": "findings->verdicted at ~0 tokens; price: TTL staleness risk",
    "max_batch_iterations": "evidence depth; more tokens, fewer judged NEEDS_REVIEW",
    "mode_b (APPSECGATE_MODE_B=1)": "file_verified basis; more tokens, NR->high-confidence",
    "mode_batch_sizes": "fewer calls, amortized prefix; price: truncation/overflow risk",
    "adaptive_max_tokens": "output budget follows batch size; price: larger reserve",
    "think=true": "more completion tokens; price for SAST verdict quality (P2 A/B)",
    "num_ctx": "larger context; fewer context_overflow NR at more prefill tokens",
}


def _load_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    runs: dict[str, Any] = {}
    for report_path in sorted(ROOT.glob(f"artifacts/{args.label}-*/report.json")):
        run_id = report_path.parent.name
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        data_dir = ROOT / "runtime" / f"data-{run_id}"
        runs[run_id] = {
            "report": report,
            "verdicts": _load_lines(data_dir / "triage_verdicts.ndjson"),
            "calls": _load_lines(data_dir / "llm_calls.ndjson"),
        }

    funnel: dict[str, Counter] = defaultdict(Counter)
    tokens: dict[str, Counter] = defaultdict(Counter)
    for run in runs.values():
        report = run["report"]
        repo = report.get("run_id", "").rsplit("-", 1)[-1]
        usage = report.get("usage") or {}
        for event in run["verdicts"]:
            mode = event.get("prompt_mode") or "unknown"
            verdict = event.get("verdict", "unknown")
            failure = event.get("failure_reason")
            funnel[mode][verdict] += 1
            if failure:
                funnel[mode][f"nr_{failure}"] += 1
            elif verdict == "NEEDS_REVIEW":
                funnel[mode]["nr_judged"] += 1
            funnel[mode]["total"] += 1
            if event.get("confidence_level") == "high":
                funnel[mode]["high_confidence"] += 1
        for call in run["calls"]:
            mode = call.get("mode") or "unknown"
            tokens[mode]["calls"] += 1
            for key in ("prompt_tokens", "completion_tokens"):
                value = call.get(key)
                if isinstance(value, int):
                    tokens[mode][key] += value
                else:
                    tokens[mode][f"{key}_missing"] += 1
        tokens["_run"]["evidence_reads"] += usage.get("evidence_reads", 0)
        tokens["_run"]["reused_verdicts"] += usage.get("reused_verdicts", 0)
        tokens["_run"]["batch_retries"] += usage.get("batch_retries", 0)

    modes = sorted(funnel)
    per_mode = {}
    for mode in modes:
        f = funnel[mode]
        t = tokens[mode]
        total = f["total"] or 1
        per_mode[mode] = {
            "findings": f["total"],
            "verdicts": {k: f[k] for k in ("TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW")},
            "nr_judged": f["judged"],
            "nr_failed": {
                reason: f[f"nr_{reason}"]
                for reason in ("context_overflow", "timeout", "llm_error", "budget_exhausted")
                if f[f"nr_{reason}"]
            },
            "high_confidence_share": round(f["high_confidence"] / total, 4),
            "calls": t["calls"],
            "prompt_tokens": t["prompt_tokens"] or None,
            "completion_tokens": t["completion_tokens"] or None,
            "tokens_per_finding": (
                round((t["prompt_tokens"] + t["completion_tokens"]) / total, 1)
                if t["prompt_tokens"] or t["completion_tokens"]
                else None
            ),
        }

    artifact = {
        "label": args.label,
        "runs": len(runs),
        "run_ids": sorted(runs),
        "per_mode": per_mode,
        "run_totals": dict(tokens["_run"]),
        "levers": LEVERS,
        "notes": [
            "per-finding tokens are call tokens divided equally across the chunk",
            "null token fields mean the provider did not report usage for those calls",
        ],
    }
    output = ROOT / "artifacts" / f"funnel-cost-{args.label}.json"
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"runs": len(runs), "modes": modes, "output": str(output)}))


if __name__ == "__main__":
    main()
