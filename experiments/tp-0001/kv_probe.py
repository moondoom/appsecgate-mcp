#!/usr/bin/env python3
"""Ollama capacity probe: context size x parallelism matrix.

Measures prompt-eval and decode rates for concurrent requests against the
LLM host directly (no LiteLLM). Goal: how much actually fits, at the
parameters the agent pipeline uses most.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("PROBE_HOST", "http://10.0.0.222:3030")
MODEL = os.environ.get("PROBE_MODEL", "hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q3_K_M")
OUTPUT = ROOT / "artifacts" / f"kv-probe-{os.environ.get('PROBE_TAG', 'baseline')}.json"

CTX_SIZES = [int(v) for v in os.environ.get("PROBE_CTX", "4096,16384,32768").split(",")]
PARALLEL = [int(v) for v in os.environ.get("PROBE_PARALLEL", "1,2,4").split(",")]
NUM_PREDICT = int(os.environ.get("PROBE_PREDICT", "128"))


def _one_request(prompt_tokens: int, salt: str) -> dict:
    # Salt first (unique prefix kills prompt cache between cells/requests),
    # then ~1 token per "word " filler covering ~70% of the window.
    prompt = f"{salt} " + "lorem ipsum dolor sit amet " * max(1, prompt_tokens // 5)
    payload = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": prompt_tokens, "num_predict": NUM_PREDICT},
        }
    ).encode()
    request = urllib.request.Request(
        f"{HOST}/api/generate", data=payload, headers={"Content-Type": "application/json"}
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=900) as response:
        result = json.load(response)
    wall = time.monotonic() - started
    prompt_rate = result.get("prompt_eval_count", 0) / max(result.get("prompt_eval_duration", 1) / 1e9, 1e-9)
    eval_rate = result.get("eval_count", 0) / max(result.get("eval_duration", 1) / 1e9, 1e-9)
    return {
        "wall_sec": round(wall, 2),
        "prompt_tokens": result.get("prompt_eval_count"),
        "prompt_tok_s": round(prompt_rate, 1),
        "eval_tokens": result.get("eval_count"),
        "eval_tok_s": round(eval_rate, 1),
    }


def _cell(ctx: int, parallel: int) -> dict:
    started = time.monotonic()
    errors = []
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [
            pool.submit(_one_request, ctx, f"probe-{time.time_ns()}-{index}")
            for index in range(parallel)
        ]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except Exception as exc:  # probe: record, don't fail the cell
                errors.append(str(exc)[:200])
    wall = time.monotonic() - started
    total_eval = sum(r["eval_tokens"] or 0 for r in results)
    return {
        "ctx": ctx,
        "parallel": parallel,
        "ok": len(results),
        "errors": errors,
        "wall_sec": round(wall, 2),
        "per_request": results,
        "agg_eval_tok_s": round(total_eval / max(wall, 1e-9), 1),
        "min_eval_tok_s": min((r["eval_tok_s"] for r in results), default=None),
        "avg_prompt_tok_s": round(
            sum(r["prompt_tok_s"] for r in results) / max(len(results), 1), 1
        ),
    }


def main() -> None:
    cells = []
    for ctx in CTX_SIZES:
        for parallel in PARALLEL:
            cell = _cell(ctx, parallel)
            cells.append(cell)
            print(json.dumps(cell))
    OUTPUT.write_text(
        json.dumps({"host": HOST, "model": MODEL, "cells": cells}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(OUTPUT), "cells": len(cells)}))


if __name__ == "__main__":
    main()
