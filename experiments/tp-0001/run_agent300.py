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
    parser.add_argument("--identity-label", help="Override project identity without renaming artifacts")
    parser.add_argument("--reuse-ttl", help="Override frozen reuse TTL for controlled validation")
    parser.add_argument("--knowledge-cutoff", help="Override cutoff; empty means no cutoff")
    return parser.parse_args()


def main() -> None:
    args = _args()
    config = json.loads((ROOT / "artifacts" / "agent300-run-config.json").read_text())
    keys = json.loads((ROOT / "runtime" / "agent300-keys.json").read_text())
    projects = args.projects
    repeat_labels = {"agent300repeat", "agent300review", "agent300adr18", "agent300fix1"}
    if projects is None and args.label in repeat_labels:
        projects = ",".join(config["repeat"])
    if projects is None:
        projects = ",".join(item["name"] for item in config["repositories"])
    knowledge_cutoff = config["master"]["knowledge_cutoff"]
    if args.label == "agent300review":
        knowledge_cutoff = config["master"].get("review_knowledge_cutoff", knowledge_cutoff)
    if args.label in {"agent300adr18", "agent300fix1"}:
        knowledge_cutoff = ""
    if args.knowledge_cutoff is not None:
        knowledge_cutoff = args.knowledge_cutoff
    identity_label = args.identity_label or (
        "agent300" if args.label in repeat_labels else args.label
    )
    env = os.environ.copy()
    env.update(
        {
            "APPSECGATE_MASTER_API_KEYS": json.dumps(keys),
            "APPSECGATE_MASTER_URL": config["master"]["url"],
            "APPSECGATE_MASTER_HOST_URL": config["master"]["host_url"],
            "APPSECGATE_KNOWLEDGE_CUTOFF": knowledge_cutoff,
            "APPSECGATE_LLM_MODEL": config["model"]["litellm_model"],
            "APPSECGATE_AGENT_MODE": config.get("agent_mode", "guided"),
            "APPSECGATE_AGENT_INTERNAL_PARALLEL": str(config.get("internal_parallel", 2)),
            "APPSECGATE_AGENT_BATCH_SORT": config.get("batch_sort", "mode_major"),
            "APPSECGATE_AGENT_REUSE_TTL": args.reuse_ttl or config.get("reuse_ttl", "1w"),
            "APPSECGATE_LLM_NUM_CTX": os.environ.get(
                "APPSECGATE_LLM_NUM_CTX"
            ) or str(config["num_ctx"]),
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
            "BENCH_PROJECT_ID_LABEL": identity_label,
            "BENCH_RESUME": "1",
            "BENCH_OUTPUT": f"{args.label}-benchmark.json",
        }
    )
    if args.no_sync:
        env["NO_SYNC"] = "1"
    subprocess.run(["python3", "benchmark_parallel.py"], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
