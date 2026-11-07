#!/usr/bin/env python3
"""GD-7 sweep analysis (ADR-0020 §3.7/§3.9).

Aggregates sweep + acceptance arm data into:
- artifacts/guided-tuning-summary.json — per-arm aggregates + G1-G5 verdicts
  plus owner-approved extras (variant arm V vs E, sustained-load clocks,
  final timeout calibration over all internal>=2 data);
- artifacts/gpu-per-arm.json — GPU util/VRAM/temp/power stats per arm;
- artifacts/model-failure-breakdown.json — NEEDS_REVIEW(model_failed) by
  reason and mode across all runs.

Arm data sources: artifacts/{sweep,acceptance}-<label>.json bench files and
runtime/data-<run_id>/{llm_calls,triage_verdicts}.ndjson. Missing files are
skipped with a note so the script is safe to run mid-sweep.
"""
from __future__ import annotations

import json
import statistics
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROMETHEUS = "http://10.0.0.222:9090"

# label -> (bench files, internal, external, batch_sort, note)
ARMS: dict[str, dict[str, Any]] = {
    "A": {"files": ["sweep-swa.json"], "internal": 1, "external": 1},
    "B": {"files": ["acceptance-accb.json", "acceptance-accb2.json"], "internal": 1, "external": 2},
    "C": {"files": ["sweep-swc.json"], "internal": 1, "external": 4},
    "D": {"files": ["acceptance-accd.json"], "internal": 2, "external": 2},
    "D2": {"files": ["sweep-swd2.json"], "internal": 2, "external": 2, "batch_sort": "none"},
    "E": {"files": ["acceptance-acce.json"], "internal": 4, "external": 1},
    "E_sustained": {"files": ["sweep-swe.json"], "internal": 4, "external": 1},
    "F": {"files": ["sweep-swf.json"], "internal": 2, "external": 1},
    "V": {"files": ["sweep-swv.json"], "internal": 4, "external": 1, "variant": True},
    "B_small": {"files": ["sweep-smb.json"], "internal": 1, "external": 2},
    "D_small": {"files": ["sweep-smd.json"], "internal": 2, "external": 2},
    "C_small": {"files": ["sweep-smc.json"], "internal": 1, "external": 4},
}

GPU_METRICS = ("gpu_utilization", "gpu_memory_used", "gpu_temperature", "gpu_power")
CLOCK_QUERIES = {
    "sm_clock_min_hz": "min_over_time(DCGM_FI_DEV_SM_CLOCK[1h])",
    "mem_clock_min_hz": "min_over_time(DCGM_FI_DEV_MEM_CLOCK[1h])",
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


def _bench_runs(files: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (runs, missing_files). Each run gets report/verdicts/calls attached."""
    runs: list[dict[str, Any]] = []
    missing: list[str] = []
    for name in files:
        path = ROOT / "artifacts" / name
        if not path.exists():
            missing.append(name)
            continue
        for cell in json.loads(path.read_text(encoding="utf-8")):
            for run in cell.get("runs", []):
                data_dir = ROOT / "runtime" / f"data-{run['run_id']}"
                report_path = ROOT / "artifacts" / run["run_id"] / "report.json"
                report = {}
                if report_path.exists():
                    try:
                        report = json.loads(report_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        pass
                runs.append(
                    {
                        **run,
                        "bench_file": name,
                        "usage": report.get("usage") or {},
                        "verdicts": _load_lines(data_dir / "triage_verdicts.ndjson"),
                        "calls": _load_lines(data_dir / "llm_calls.ndjson"),
                        "prometheus": cell.get("prometheus", {}),
                        "bench_window": (cell.get("started_at"), cell.get("ended_at")),
                    }
                )
    return runs, missing


def _drift(base: list[dict[str, Any]], cand: list[dict[str, Any]]) -> dict[str, Any]:
    """Verdict drift on the intersection of judged findings (G3'/G5 rule)."""
    judged = {"TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"}

    def by_id(events: list[dict[str, Any]]) -> dict[str, str]:
        return {
            e["fp"]: e["verdict"]
            for e in events
            if e.get("fp") and e.get("verdict") in judged and not e.get("failure_reason")
        }

    a, b = by_id(base), by_id(cand)
    common = sorted(set(a) & set(b))
    flips = [fid for fid in common if a[fid] != b[fid]]
    return {"base": len(a), "cand": len(b), "common": len(common), "drift": len(flips), "flips": flips[:20]}


def _gpu_stats(prometheus: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for name in GPU_METRICS:
        series = (prometheus.get(name) or {}).get("data", {}).get("result", [])
        values = [float(v) for point in series for _, v in point.get("values", [])]
        if values:
            out[name] = {
                "avg": round(statistics.fmean(values), 3),
                "max": round(max(values), 3),
                "min": round(min(values), 3),
            }
    return out


def _prom_query(query: str) -> float | None:
    params = urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(f"{PROMETHEUS}/api/v1/query?{params}", timeout=15) as resp:
            result = json.load(resp).get("data", {}).get("result", [])
    except OSError:
        return None
    if not result:
        return None
    try:
        return float(result[0]["value"][1])
    except (KeyError, ValueError, IndexError):
        return None


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, round(q * (len(sorted_values) - 1)))
    return sorted_values[idx]


def main() -> None:
    arms: dict[str, Any] = {}
    notes: list[str] = []
    for label, spec in ARMS.items():
        runs, missing = _bench_runs(spec["files"])
        if missing:
            notes.append(f"{label}: missing bench files {missing}, arm skipped")
        if not runs:
            continue
        by_project: dict[str, Any] = {}
        for run in runs:
            usage = run["usage"]
            proj = by_project.setdefault(
                run["project"],
                {"durations": [], "tokens": [], "runs": [], "model_failed": Counter(), "verdict_rows": [], "call_rows": []},
            )
            proj["durations"].append(run.get("duration_sec"))
            proj["tokens"].append(run.get("total_tokens"))
            proj["runs"].append(run["run_id"])
            proj["verdict_rows"].extend(run["verdicts"])
            proj["call_rows"].extend(run["calls"])
            for key, value in usage.items():
                if key.startswith("model_failed_") and isinstance(value, int) and value:
                    proj["model_failed"][key.removeprefix("model_failed_")] += value
        arms[label] = {
            "spec": {k: v for k, v in spec.items() if k != "files"},
            "projects": {
                project: {
                    "runs": data["runs"],
                    "wall_sec_p99": round(_percentile(sorted(d for d in data["durations"] if d), 0.99), 1),
                    "wall_sec_avg": round(statistics.fmean(d for d in data["durations"] if d), 1),
                    "total_tokens": sum(t for t in data["tokens"] if t),
                    "model_failed": dict(data["model_failed"]),
                }
                for project, data in by_project.items()
            },
            "_raw": runs,
            "_by_project": by_project,
        }

    def project_wall(arm: str, project: str) -> float | None:
        proj = arms.get(arm, {}).get("projects", {}).get(project)
        return proj["wall_sec_p99"] if proj else None

    gates: dict[str, Any] = {}

    # G1: wall(B)/wall(D) on atopile.
    b_wall, d_wall = project_wall("B", "atopile"), project_wall("D", "atopile")
    if b_wall and d_wall:
        speedup = round(b_wall / d_wall, 3)
        gates["G1_speedup_D_vs_B_atopile"] = {
            "value": speedup,
            "pass": speedup >= 1.15,
            "note": "1.05-1.15 is the ambiguous zone, E/F are tiebreakers",
        }

    # G2: D vs C vs E per repo (heavy: atopile/costrict/CodeWiki; small: structlog/aitextgen).
    g2 = {}
    for project in ("atopile", "costrict", "CodeWiki"):
        entry = {}
        for arm in ("B", "C", "D", "E", "E_sustained", "F"):
            wall = project_wall(arm, project)
            if wall:
                entry[arm] = wall
        if entry:
            g2[project] = {"wall_sec": entry, "winner": min(entry, key=entry.get)}
    for project in ("structlog", "aitextgen"):
        entry = {}
        for arm in ("B_small", "C_small", "D_small"):
            wall = project_wall(arm, project)
            if wall:
                entry[arm] = wall
        if entry:
            g2[project] = {"wall_sec": entry, "winner": min(entry, key=entry.get)}
    if g2:
        gates["G2_per_repo_winners"] = {"values": g2, "pass": None, "note": "per-class winners allowed"}

    # G3: D vs D2 (batch_sort=none) on atopile. Cache counters unavailable -> wall-only.
    d2_wall = project_wall("D2", "atopile")
    if d_wall and d2_wall:
        delta = round(abs(d2_wall - d_wall) / d_wall, 4)
        gates["G3_sort_D_vs_D2_atopile"] = {
            "wall_delta": delta,
            "cache_hit_rate": "unavailable (cache_metrics_unavailable=1), wall-only rule",
            "pass_remove_sorting": delta < 0.03,
            "note": "sorting kept by default unless wall delta < 3%",
        }

    # G4: winner per-repo P99 vs A (A measured on atopile/costrict only).
    g4 = {}
    winners = g2.get("atopile", {}).get("winner"), g2.get("costrict", {}).get("winner")
    for project, winner in zip(("atopile", "costrict"), winners, strict=False):
        a_wall, w_wall = project_wall("A", project), project_wall(winner, project) if winner else None
        if a_wall and w_wall:
            g4[project] = {"winner": winner, "ratio_vs_A": round(w_wall / a_wall, 3), "pass": w_wall <= a_wall * 1.10}
    if g4:
        gates["G4_winner_vs_A"] = {"values": g4, "pass": all(v["pass"] for v in g4.values())}

    # G5: verdict drift winner vs B on CodeWiki/structlog (must be 0).
    g5 = {}
    pairs = [("CodeWiki", "B", "D"), ("structlog", "B_small", "D_small")]
    for project, base_arm, cand_arm in pairs:
        base = arms.get(base_arm, {}).get("_by_project", {}).get(project)
        cand = arms.get(cand_arm, {}).get("_by_project", {}).get(project)
        if base and cand:
            g5[project] = _drift(base["verdict_rows"], cand["verdict_rows"])
    if g5:
        gates["G5_drift_winner_vs_B"] = {"values": g5, "pass": all(v["drift"] == 0 for v in g5.values())}

    # Extra 1 (owner-approved): variant arm V (per-mode batch sizes + adaptive) vs E on atopile.
    extras: dict[str, Any] = {}
    v_wall, e_wall = project_wall("V", "atopile"), project_wall("E", "atopile")
    v_proj = arms.get("V", {}).get("_by_project", {}).get("atopile")
    e_proj = arms.get("E", {}).get("_by_project", {}).get("atopile")
    if v_proj and e_proj and v_wall and e_wall:

        def tok_per_finding(proj: dict[str, Any]) -> float | None:
            judged = sum(1 for e in proj["verdict_rows"] if e.get("verdict"))
            tokens = sum(
                (c.get("prompt_tokens") or 0) + (c.get("completion_tokens") or 0) for c in proj["call_rows"]
            )
            return round(tokens / judged, 1) if judged else None

        extras["V_vs_E_atopile"] = {
            "wall_ratio": round(v_wall / e_wall, 3),
            "tokens_per_finding": {"V": tok_per_finding(v_proj), "E": tok_per_finding(e_proj)},
            "drift": _drift(e_proj["verdict_rows"], v_proj["verdict_rows"]),
        }

    # Extra 2: sustained-load clock minima over the E_sustained window.
    clock_stats = {name: _prom_query(query) for name, query in CLOCK_QUERIES.items()}
    extras["sustained_load_clocks"] = {
        "values": clock_stats,
        "note": "None means the DCGM clock metric is not exported; use gpu-per-arm.json power/temp instead",
    }

    # Extra 3: final timeout calibration over all internal>=2 call data.
    d_calls = [
        c["wall_ms"]
        for label in ("D", "D2", "D_small")
        for run in arms.get(label, {}).get("_raw", [])
        for c in run["calls"]
        if isinstance(c.get("wall_ms"), int)
    ]
    if d_calls:
        d_calls.sort()
        p99 = _percentile(d_calls, 0.99)
        extras["timeout_calibration"] = {
            "calls": len(d_calls),
            "p50_ms": _percentile(d_calls, 0.50),
            "p95_ms": _percentile(d_calls, 0.95),
            "p99_ms": p99,
            "p999_ms": _percentile(d_calls, 0.999),
            "above_s": {str(t): round(sum(1 for v in d_calls if v > t * 1000) / len(d_calls), 4) for t in (90, 120, 180)},
            "derived_timeout_s": int(((p99 * 1.5) / 1000 + 29) // 30 * 30),
        }

    reserved_values: list[int] = []
    for ledger in ROOT.glob("runtime/data-*/reserved_tokens.ndjson"):
        for row in _load_lines(ledger):
            value = row.get("reserved_tokens")
            if isinstance(value, int):
                reserved_values.append(value)
    if reserved_values:
        reserved_values.sort()
        p95 = _percentile(reserved_values, 0.95)
        extras.setdefault("timeout_calibration", {})["per_finding_cap"] = {
            "findings": len(reserved_values),
            "p95": p95,
            "p99": _percentile(reserved_values, 0.99),
            "max": reserved_values[-1],
            "derived_cap": int(p95 * 1.5),
            "note": "reserved-token charges only (ADR-0020 §3.5 step 4); ledger starts with GD-15 runs",
        }
    elif "timeout_calibration" in extras:
        extras["timeout_calibration"]["per_finding_cap"] = (
            "pending reserved-token ledger (ADR-0020 §1.3.4, GD-15 backlog)"
        )

    # gpu-per-arm.json
    gpu_per_arm = {}
    for label, arm in arms.items():
        stats: dict[str, Any] = {}
        for run in arm["_raw"]:
            run_stats = _gpu_stats(run["prometheus"])
            for metric, values in run_stats.items():
                acc = stats.setdefault(metric, {"avg": [], "max": [], "min": []})
                acc["avg"].append(values["avg"])
                acc["max"].append(values["max"])
                acc["min"].append(values["min"])
        gpu_per_arm[label] = {
            metric: {
                "avg": round(statistics.fmean(v["avg"]), 3),
                "max": round(max(v["max"]), 3),
                "min": round(min(v["min"]), 3),
            }
            for metric, v in stats.items()
        }

    # model-failure-breakdown.json
    breakdown: dict[str, Counter] = {}
    for label, arm in arms.items():
        counter = breakdown.setdefault(label, Counter())
        for run in arm["_raw"]:
            for event in run["verdicts"]:
                if event.get("failure_reason"):
                    counter[f"{event.get('prompt_mode') or 'unknown'}:{event['failure_reason']}"] += 1

    summary = {
        "arms": {label: {k: v for k, v in arm.items() if not k.startswith("_")} for label, arm in arms.items()},
        "gates": gates,
        "extras": extras,
        "notes": notes,
    }
    outputs = {
        "guided-tuning-summary.json": summary,
        "gpu-per-arm.json": gpu_per_arm,
        "model-failure-breakdown.json": {k: dict(v) for k, v in breakdown.items()},
    }
    for name, payload in outputs.items():
        (ROOT / "artifacts" / name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(json.dumps({"arms": sorted(arms), "gates": sorted(gates), "notes": notes}))


if __name__ == "__main__":
    main()
