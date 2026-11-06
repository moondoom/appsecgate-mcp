#!/usr/bin/env python3
"""Synthetic LLM throughput matrix — native ollama API, runs on mgmt (10.0.0.222).

Measures prefill/decode tokens/s (ollama-reported durations) across
parallelism x num_ctx, 5 repeats each, with GPU/CPU snapshots from
local Prometheus per iteration window.

Run on mgmt: ollama at 127.0.0.1:11434, Prometheus at 127.0.0.1:9090.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
PROMETHEUS = os.environ.get("PROM_URL", "http://127.0.0.1:9090")
MODEL = "hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q3_K_M"

FILLER = "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod "
PREDICT_TOKENS = 512
PROMPT_PREFIX = (
    "Summarize the following text in one paragraph. Reply with plain prose only.\n\n"
)

PROM_QUERIES = {
    "gpu_util_avg": "avg(nvidia_smi_utilization_gpu_ratio)",
    "gpu_util_max": "max(nvidia_smi_utilization_gpu_ratio)",
    "gpu_power_avg_w": "avg(nvidia_smi_power_draw_watts)",
    "gpu_mem_used_bytes": "max(nvidia_smi_memory_used_bytes)",
    "gpu_mem_total_bytes": "max(nvidia_smi_memory_total_bytes)",
    "cpu_user_avg": "avg(rate(node_cpu_seconds_total{mode='user'}[30s]))",
    "cpu_system_avg": "avg(rate(node_cpu_seconds_total{mode='system'}[30s]))",
    "cpu_iowait_avg": "avg(rate(node_cpu_seconds_total{mode='iowait'}[30s]))",
    "cpu_mem_used_bytes": "max(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)",
    "cpu_mem_total_bytes": "max(node_memory_MemTotal_bytes)",
}


def _post(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _prom_range(query: str, start: float, end: float, step: int = 15) -> list[float]:
    params = urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": step})
    with urllib.request.urlopen(f"{PROMETHEUS}/api/v1/query_range?{params}", timeout=30) as r:
        result = json.load(r)["data"]["result"]
    if not result:
        return []
    return [float(v[1]) for v in result[0]["values"]]


def _prom_snapshot(start: float, end: float) -> dict:
    snapshot = {}
    for name, query in PROM_QUERIES.items():
        values = _prom_range(query, start, end)
        if not values:
            snapshot[name] = None
        elif name.endswith("_max") or "mem" in name:
            snapshot[name] = round(max(values), 4)
        else:
            snapshot[name] = round(sum(values) / len(values), 4)
    return snapshot


def _build_prompt(ctx: int) -> str:
    # ~1 token per filler word; reserve space for completion + template.
    target_words = ctx - PREDICT_TOKENS - 128
    words = FILLER.split()
    body = " ".join(words[i % len(words)] for i in range(target_words))
    return PROMPT_PREFIX + body


def _one_request(prompt: str, ctx: int, timeout: float, salt: int, exact_ctx: bool) -> dict:
    # Default: keep the already-loaded 32k runner for prompts up to 32k —
    # a smaller num_ctx would force a reload. exact_ctx mode deliberately
    # requests the exact context (small runner, reload cost) for lane tests.
    num_ctx = ctx if (exact_ctx or ctx > 32768) else 32768
    payload = {
        "model": MODEL,
        "prompt": f"{prompt}\n\n[request {salt}]",  # salt defeats prompt cache
        "stream": False,
        "options": {"num_ctx": num_ctx, "num_predict": PREDICT_TOKENS, "temperature": 0},
    }
    started = time.time()
    try:
        data = _post(f"{OLLAMA}/api/generate", payload, timeout)
    except Exception as exc:  # noqa: BLE001 - record and continue the matrix
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "wall_s": time.time() - started}
    prefill_s = data.get("prompt_eval_duration", 0) / 1e9
    decode_s = data.get("eval_duration", 0) / 1e9
    return {
        "ok": True,
        "wall_s": round(time.time() - started, 2),
        "prompt_tokens": data.get("prompt_eval_count"),
        "completion_tokens": data.get("eval_count"),
        "prefill_tps": round(data.get("prompt_eval_count", 0) / prefill_s, 1) if prefill_s else None,
        "decode_tps": round(data.get("eval_count", 0) / decode_s, 1) if decode_s else None,
        "load_ms": round(data.get("load_duration", 0) / 1e6),
    }


def _run_cell(
    parallelism: int, ctx: int, repeats: int, timeout: float, exact_ctx: bool = False
) -> dict:
    prompt = _build_prompt(ctx)
    cell = {"parallelism": parallelism, "num_ctx": ctx, "exact_ctx": exact_ctx, "iterations": []}
    for iteration in range(repeats):
        wall_start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as pool:
            results = list(
                pool.map(
                    lambda i: _one_request(prompt, ctx, timeout, iteration * 100 + i, exact_ctx),
                    range(parallelism),
                )
            )
        wall_end = time.time()
        ok = [r for r in results if r["ok"]]
        cell["iterations"].append(
            {
                "iteration": iteration,
                "wall_s": round(wall_end - wall_start, 2),
                "ok": len(ok),
                "errors": [r["error"] for r in results if not r["ok"]],
                "requests": results,
                "aggregate_decode_tps": round(sum(r["decode_tps"] or 0 for r in ok), 1),
                "aggregate_prefill_tps": round(sum(r["prefill_tps"] or 0 for r in ok), 1),
                "prometheus": _prom_snapshot(wall_start - 5, wall_end + 5),
            }
        )
        last = cell["iterations"][-1]
        print(
            json.dumps(
                {
                    "cell": f"p{parallelism}/ctx{ctx}",
                    "iteration": iteration,
                    "ok": last["ok"],
                    "wall_s": last["wall_s"],
                    "agg_decode_tps": last["aggregate_decode_tps"],
                    "prompt_tokens": [r.get("prompt_tokens") for r in results if r["ok"]],
                }
            ),
            flush=True,
        )
        time.sleep(3)
    return cell


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parallelism", default="1,2,3,4")
    parser.add_argument("--contexts", default="4096,8192,16384,32768,65536")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--exact-ctx", action="store_true", help="pass num_ctx as-is (small runners)")
    parser.add_argument("--output", default="llm-perf-matrix.json")
    return parser.parse_args()


def main() -> None:
    args = _args()
    parallelisms = [int(v) for v in args.parallelism.split(",")]
    contexts = [int(v) for v in args.contexts.split(",")]
    report = {
        "model": MODEL,
        "ollama": OLLAMA,
        "predict_tokens": PREDICT_TOKENS,
        "repeats": args.repeats,
        "exact_ctx": args.exact_ctx,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cells": [],
    }
    for parallelism in parallelisms:
        for ctx in contexts:
            report["cells"].append(
                _run_cell(parallelism, ctx, args.repeats, args.timeout, args.exact_ctx)
            )
            Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
            time.sleep(5)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"cells": len(report["cells"]), "output": args.output}))


if __name__ == "__main__":
    main()
