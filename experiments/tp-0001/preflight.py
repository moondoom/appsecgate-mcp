#!/usr/bin/env python3
"""GD-11 pre-flight environment check (ADR-0019 §1.4.1, §1.5).

Fail-fast before any LLM call. Checks:
  1. Slot budget: APPSECGATE_AGENT_INTERNAL_PARALLEL x EXTERNAL_P <= NUM_PARALLEL_MAX.
  2. Model digest: the configured model exists on the LiteLLM endpoint.
  3. Prometheus metric names are queryable; scrape interval is recorded.

Writes a JSON artifact and exits non-zero on any failed check.
Host tooling only: network access is allowed here (never from the MCP server).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from typing import Any

EXPECTED_PROMETHEUS_METRICS = [
    "DCGM_FI_DEV_SM_CLOCK",
    "DCGM_FI_DEV_MEM_CLOCK",
    "DCGM_FI_DEV_GPU_UTIL",
    "DCGM_FI_DEV_FB_USED",
    "DCGM_FI_DEV_POWER_USAGE",
    "node_cpu_seconds_total",
    "node_memory_MemAvailable_bytes",
]


def _get_json(url: str, api_key: str = "", timeout: float = 10) -> Any:
    request = urllib.request.Request(url)
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _check_slot_budget(errors: list[str]) -> dict[str, int]:
    internal = int(os.environ.get("APPSECGATE_AGENT_INTERNAL_PARALLEL", "2"))
    external = int(os.environ.get("EXTERNAL_P", os.environ.get("BENCH_PARALLELISM", "1")))
    maximum = int(os.environ.get("APPSECGATE_NUM_PARALLEL_MAX", "4"))
    if internal * external > maximum:
        errors.append(
            f"slot budget violated: internal_parallel={internal} x external_p={external} "
            f"> num_parallel_max={maximum}"
        )
    return {"internal_parallel": internal, "external_p": external, "num_parallel_max": maximum}


def _check_model(errors: list[str]) -> dict[str, Any]:
    llm_url = os.environ.get("APPSECGATE_LLM_URL", "").rstrip("/")
    model = os.environ.get("APPSECGATE_LLM_MODEL", "")
    api_key = os.environ.get("APPSECGATE_LLM_API_KEY", "")
    if not llm_url or not model:
        errors.append("APPSECGATE_LLM_URL and APPSECGATE_LLM_MODEL are required")
        return {}
    try:
        payload = _get_json(f"{llm_url}/models", api_key)
    except Exception as exc:
        errors.append(f"model endpoint unreachable: {exc}")
        return {}
    entries = payload.get("data", []) if isinstance(payload, dict) else []
    match = next((item for item in entries if item.get("id") == model), None)
    if match is None:
        known = [item.get("id") for item in entries]
        errors.append(f"model {model!r} not served; available: {known}")
        return {}
    return {"model": model, "model_info": match}


def _check_prometheus(errors: list[str]) -> dict[str, Any]:
    base = os.environ.get("PROMETHEUS_URL", "").rstrip("/")
    scrape = os.environ.get("PROM_SCRAPE_INTERVAL_S", "")
    if not base:
        errors.append("PROMETHEUS_URL is required")
        return {}
    found: dict[str, bool] = {}
    for metric in EXPECTED_PROMETHEUS_METRICS:
        try:
            payload = _get_json(f"{base}/api/v1/query?query={metric}")
            found[metric] = bool(payload.get("data", {}).get("result"))
        except Exception as exc:
            errors.append(f"prometheus query failed for {metric}: {exc}")
            found[metric] = False
    missing = [name for name, ok in found.items() if not ok]
    if missing:
        errors.append(f"prometheus metrics missing: {missing}")
    if not scrape:
        errors.append("PROM_SCRAPE_INTERVAL_S must be recorded explicitly")
    attribution = "window_overlap" if scrape == "1" else "run_level_only"
    return {
        "prometheus_url": base,
        "metrics": found,
        "scrape_interval_s": scrape or None,
        "gpu_attribution": attribution,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="", help="artifact path (default: stdout only)")
    args = parser.parse_args()

    errors: list[str] = []
    artifact = {
        "at": datetime.now(UTC).isoformat(),
        "num_ctx": int(os.environ.get("APPSECGATE_LLM_NUM_CTX", "36864")),
        "slot_budget": _check_slot_budget(errors),
        "model": _check_model(errors),
        "prometheus": _check_prometheus(errors),
        "ok": not errors,
        "errors": errors,
    }
    text = json.dumps(artifact, ensure_ascii=False, indent=2, default=str)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            output.write(text + "\n")
    print(text)
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
