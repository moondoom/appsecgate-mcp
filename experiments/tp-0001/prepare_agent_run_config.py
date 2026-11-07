#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LABELS = ("agent300-preflight", "agent300", "agent300repeat")
REPEAT = (
    "structlog",
    "aitextgen",
    "claude-code-skills",
    "CodeWiki",
    "zep",
    "AIWriteX",
    "bitcore",
    "openbot",
    "overseerr",
    "Huatuo-Llama-Med-Chinese",
)


def main() -> None:
    manifest = json.loads((ROOT / "artifacts" / "agent300-manifest.json").read_text())
    freeze = json.loads((ROOT / "artifacts" / "stage2-freeze.json").read_text())
    prompt_path = ROOT.parents[1] / "mcp-server/src/appsecgate_mcp/agent/prompts/agent_guided.md"
    prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    rules_path = ROOT / "runtime" / "research-rules" / "rules" / ".external-rules.json"
    if not rules_path.is_file():
        raise SystemExit("research rules missing; run make experiment-semgrep-rules-prepare")
    external_rules = json.loads(rules_path.read_text())
    image_id = subprocess.run(
        ["docker", "image", "inspect", "moondoom/appsecgate-mcp:0.1.0", "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    knowledge_cutoff = datetime.now(timezone.utc).isoformat()
    config = {
        "agent_version": "agent-rc-v1",
        "agent_mode": "guided",
        "internal_parallel": 2,
        "batch_sort": "mode_major",
        "reuse_ttl": "1h",
        "generated_at": knowledge_cutoff,
        "model": freeze["model"],
        "image": {"tag": "moondoom/appsecgate-mcp:0.1.0", "id": image_id},
        "prompt_sha256": prompt_hash,
        "external_rules": external_rules,
        "parallelism": 1,
        "num_ctx": 32768,
        "max_iterations": 500,
        "max_restarts": 5,
        "max_compactions": 10,
        "max_tokens": 2_000_000,
        "max_context_chars": 120_000,
        "master": {
            "url": "http://appsecgate-agent300-master:8000",
            "host_url": "http://127.0.0.1:8001",
            "knowledge_cutoff": knowledge_cutoff,
            "review_knowledge_cutoff": "2026-11-06T06:44:03.327213+00:00",
        },
        "repositories": manifest,
        "repeat": list(REPEAT),
        "expansion": {
            "block_size": 100,
            "max_repositories": 1000,
            "ci_half_width_percentage_points": 5,
            "min_human_tp_per_category": 30,
        },
    }
    (ROOT / "artifacts" / "agent300-run-config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    )

    keys = {"agent-dev-knowledge": "agent-dev-knowledge-key"}
    for label in LABELS:
        for item in manifest:
            run_id = f"{label}-gemmaq3-p{config['parallelism']}-{item['name']}"
            keys[f"{item['name']}-tp0001-{run_id}"] = f"agent300-{label}-{item['name']}-key"
    (ROOT / "runtime" / "agent300-keys.json").write_text(
        json.dumps(keys, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps({"repositories": len(manifest), "repeat": len(REPEAT), "keys": len(keys)}))


if __name__ == "__main__":
    main()
