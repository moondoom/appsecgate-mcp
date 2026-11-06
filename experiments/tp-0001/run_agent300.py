#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frozen agent300 configuration")
    parser.add_argument("--label", default="agent300-preflight")
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--projects", help="Optional comma-separated subset for a readiness smoke")
    return parser.parse_args()


def main() -> None:
    args = _args()
    config = json.loads((ROOT / "artifacts" / "agent300-run-config.json").read_text())
    keys = json.loads((ROOT / "runtime" / "agent300-keys.json").read_text())
    projects = args.projects
    if projects is None and args.label == "agent300repeat":
        projects = ",".join(config["repeat"])
    if projects is None:
        projects = ",".join(item["name"] for item in config["repositories"])
    env = os.environ.copy()
    env.update(
        {
            "APPSECGATE_MASTER_API_KEYS": json.dumps(keys),
            "APPSECGATE_MASTER_URL": config["master"]["url"],
            "APPSECGATE_MASTER_HOST_URL": config["master"]["host_url"],
            "APPSECGATE_KNOWLEDGE_CUTOFF": config["master"]["knowledge_cutoff"],
            "APPSECGATE_LLM_MODEL": config["model"]["litellm_model"],
            "APPSECGATE_AGENT_MODE": config.get("agent_mode", "guided"),
            "APPSECGATE_LLM_NUM_CTX": str(config["num_ctx"]),
            "APPSECGATE_AGENT_MAX_ITERATIONS": str(config["max_iterations"]),
            "APPSECGATE_AGENT_MAX_RESTARTS": str(config["max_restarts"]),
            "APPSECGATE_AGENT_MAX_COMPACTIONS": str(config["max_compactions"]),
            "APPSECGATE_AGENT_MAX_TOKENS": str(config["max_tokens"]),
            "APPSECGATE_AGENT_MAX_CONTEXT_CHARS": str(config["max_context_chars"]),
            "DOCKER_NETWORK": "appsecgate-mcp_appsecgate",
            "BENCH_MODELS": "gemmaq3",
            "BENCH_PARALLELISM": str(config["parallelism"]),
            "BENCH_PROJECTS": projects,
            "BENCH_LABEL": args.label,
            "BENCH_RESUME": "1",
            "BENCH_OUTPUT": f"{args.label}-benchmark.json",
        }
    )
    if args.no_sync:
        env["NO_SYNC"] = "1"
    subprocess.run(["python3", "benchmark_parallel.py"], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
