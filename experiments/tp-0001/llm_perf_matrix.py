#!/usr/bin/env python3
"""Synthetic LLM throughput matrix for the 10.0.0.222 LLM host.

Measures prefill (time to first token) and decode tokens/s across
parallelism x num_ctx configurations, 5 repeats each, against the same
LiteLLM proxy endpoint the agent uses, and snapshots GPU/CPU from
Prometheus per measurement window.

Run only when the agent benchmark is idle: the test needs the whole GPU.
LITELLM_API_KEY is read from the repo .env at runtime, never printed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LLM_URL = "http://10.0.0.222:4000/v1/chat/completions"
PROMETHEUS = "http://10.0.0.222:9090"
ENV_FILE = ROOT.parent.parent / ".env"

# One filler token ~= one word here; sized so prompt_tokens ~= ctx - reserve.
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
    "cpu_mem_used_bytes": "max(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)",
    "cpu_mem_total_bytes": "max(node_memory_MemTotal_bytes)",
    "cpu_user_avg": "avg(rate(node_cpu_seconds_total{mode='user'}[30s]))",
    "cpu_system_avg": "avg(rate(node_cpu_seconds_total{mode='system'}[30s]))",
    "cpu_iowait_avg": "avg(rate(node_cpu_seconds_total{mode='iowait'}[30s]))",
}


def _load_api_key() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("LITELLM_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("LITELLM_API_KEY not found in .env")


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
    # gemma BPE ~1 token per word for this filler; keep 15% headroom under ctx.
    target_words = ctx - PREDICT_TOKENS - 128
    words = FILLER.split()
    body = " ".join(words[i % len(words)] for i in range(target_words))
    return PROMPT_PREFIX + body


def _one_request(
    prompt: str, ctx: int, timeout: float, model: str, api_key: str, salt: int, stagger: float = 0
) -> dict:
    if stagger:
        time.sleep(random.uniform(0, stagger))
    # num_ctx MUST be explicit: without it the proxy/ollama path truncates
    # the prompt to ~2051 tokens. Salt defeats the ollama prefix cache.
    num_ctx = ctx
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": f"[request {salt}]\n\n{prompt}"}],
        "max_tokens": PREDICT_TOKENS,
        "temperature": 0,
        "num_ctx": num_ctx,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        LLM_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    started = time.time()
    ttft = None
    usage = {}
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw in response:
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line[5:])
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if choices and choices[0].get("delta", {}).get("content") and ttft is None:
                    ttft = time.time() - started
    except Exception as exc:  # noqa: BLE001 - record and continue the matrix
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "wall_s": time.time() - started}
    wall = time.time() - started
    completion = usage.get("completion_tokens", 0)
    decode_window = wall - ttft if ttft is not None else None
    return {
        "ok": True,
        "wall_s": round(wall, 2),
        "ttft_s": round(ttft, 2) if ttft is not None else None,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": completion,
        "prefill_tps": round(usage.get("prompt_tokens", 0) / ttft, 1) if ttft else None,
        "decode_tps": round(completion / decode_window, 1) if decode_window else None,
    }


def _run_cell(
    parallelism: int, ctx: int, repeats: int, timeout: float, model: str, key: str, stagger: float = 0
) -> dict:
    prompt = _build_prompt(ctx)
    cell = {"parallelism": parallelism, "num_ctx": ctx, "stagger": stagger, "iterations": []}
    for iteration in range(repeats):
        wall_start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as pool:
            results = list(
                pool.map(
                    lambda i: _one_request(
                        prompt, ctx, timeout, model, key, iteration * 100 + i, stagger
                    ),
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
                "prometheus": _prom_snapshot(wall_start - 5, wall_end + 5),
            }
        )
        print(
            json.dumps(
                {
                    "cell": f"p{parallelism}/ctx{ctx}",
                    "iteration": iteration,
                    "ok": len(ok),
                    "wall_s": cell["iterations"][-1]["wall_s"],
                    "agg_decode_tps": cell["iterations"][-1]["aggregate_decode_tps"],
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
    parser.add_argument("--stagger", type=float, default=0, help="max random start delay per request, s")
    parser.add_argument("--output", default=str(ROOT / "runtime" / "llm-perf-matrix.json"))
    return parser.parse_args()


def main() -> None:
    args = _args()
    api_key = _load_api_key()
    run_config = json.loads((ROOT / "artifacts" / "agent300-run-config.json").read_text())
    model = run_config["model"]["litellm_model"]
    parallelisms = [int(v) for v in args.parallelism.split(",")]
    contexts = [int(v) for v in args.contexts.split(",")]
    report = {
        "model": model,
        "llm_url": LLM_URL,
        "predict_tokens": PREDICT_TOKENS,
        "repeats": args.repeats,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cells": [],
    }
    for parallelism in parallelisms:
        for ctx in contexts:
            report["cells"].append(_run_cell(parallelism, ctx, args.repeats, args.timeout, model, api_key, args.stagger))
            Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
            time.sleep(5)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"cells": len(report["cells"]), "output": args.output}))


if __name__ == "__main__":
    main()
