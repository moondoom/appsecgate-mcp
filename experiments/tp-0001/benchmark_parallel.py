#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
PROMETHEUS = "http://10.0.0.222:9090"
MODELS = {
    "qwen": "ollama/qwen3.8:27b",
    "glm": "ollama/glm-4.7-flash:latest",
    "glmq3": "ollama/hf.co/unsloth/GLM-4.7-Flash-GGUF:UD-Q3_K_XL",
    "gemma4": "ollama/gemma4:26b",
    "qwenmtp": "ollama/qwen3.8:27b-mtp-q4_K_M",
    "qwenq3": "ollama/hf.co/bartowski/Qwen3.8-27B-GGUF:Q3_K_M",
    "qwengsq": "ollama/incu6us/qwen3.8-gsq:27b-iq3_s",
    "gemmaq3": "ollama/hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q3_K_M",
    "gemmaq3cpu": "ollama/gemmaq3-cpu",
    "deepseek": "a/deepseek-v4.1-flash",
    "qwen35-9b": "ollama/qwen3.5:9b",
    "gemma4-12b": "ollama/gemma4:12b",
    "qwen35-4b": "ollama/qwen3.5:4b",
}
QUERIES = {
    "gpu_utilization": "nvidia_smi_utilization_gpu_ratio",
    "gpu_memory_used": "nvidia_smi_memory_used_bytes",
    "gpu_temperature": "nvidia_smi_temperature_gpu",
    "gpu_power": "nvidia_smi_power_draw_watts",
    "litellm_in_flight": "litellm_in_flight_requests",
    "litellm_api_latency": "rate(litellm_llm_api_latency_metric_sum[1m])",
    "litellm_api_requests": "rate(litellm_llm_api_latency_metric_count[1m])",
    "litellm_queue_latency": "rate(litellm_request_queue_time_seconds_sum[1m])",
    "litellm_output_token_latency": "rate(litellm_deployment_latency_per_output_token_sum[1m])",
    "node_load1": "node_load1",
    "node_memory_available": "node_memory_MemAvailable_bytes",
}


def prometheus_range(query: str, start: float, end: float) -> dict:
    params = urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": 5})
    with urllib.request.urlopen(f"{PROMETHEUS}/api/v1/query_range?{params}", timeout=30) as response:
        return json.load(response)


def project_id_for(project: str, run_id: str) -> str:
    override = os.environ.get("APPSECGATE_PROJECT_ID")
    if override:
        return override
    label = os.environ.get("BENCH_LABEL", "bench")
    identity_label = os.environ.get("BENCH_PROJECT_ID_LABEL", label)
    identity_run_id = run_id.replace(f"{label}-", f"{identity_label}-", 1)
    prefix = project if project != "pygoat" else "pygoat"
    return f"{prefix}-tp0001-{identity_run_id}"


def run_one(
    model: str, llm_model: str, parallelism: int, index: int, keys: dict, project: str = "pygoat"
) -> dict:
    label = os.environ.get("BENCH_LABEL", "bench")
    if project == "pygoat":
        run_id = f"{label}-{model}-p{parallelism}-{index:02d}"
    else:
        run_id = f"{label}-{model}-p{parallelism}-{project}"
    project_id = project_id_for(project, run_id)
    env = os.environ.copy()
    env.update(
        RUN_ID=run_id,
        PROJECT=str(ROOT / "repos" / project),
        DATA_DIR=str(ROOT / "runtime" / f"data-{run_id}"),
        ARTIFACT_DIR=str(ROOT / "artifacts" / run_id),
        APPSECGATE_PROJECT_ID=project_id,
        APPSECGATE_MASTER_API_KEY=keys.get(project_id, ""),
        APPSECGATE_LLM_MODEL=llm_model,
        APPSECGATE_AGENT_INTERNAL_PARALLEL=os.environ.get(
            "APPSECGATE_AGENT_INTERNAL_PARALLEL", "2"
        ),
        APPSECGATE_AGENT_BATCH_SORT=os.environ.get(
            "APPSECGATE_AGENT_BATCH_SORT", "mode_major"
        ),
        CACHE_DIR=str(ROOT / "runtime" / "data-gemma-docker-preflight-001"),
    )
    artifact = ROOT / "artifacts" / run_id
    report_path = artifact / "report.json"
    if os.environ.get("BENCH_RESUME") == "1" and report_path.exists():
        previous = json.loads(report_path.read_text() or "{}")
        if previous.get("exit_reason") in {"report_generated", "gate_block"}:
            return {
                "run_id": run_id,
                "project": project,
                "exit": 0,
                "exit_reason": previous["exit_reason"],
                "duration_sec": previous.get("duration_sec", 0),
                "wall_sec": 0,
                "findings_total": previous.get("findings_total") or previous.get("total_findings"),
                "protocol_retries": 0,
                "total_tokens": previous.get("usage", {}).get("total_tokens"),
                "f1": None,
                "resumed": True,
            }
    started = time.monotonic()
    completed = subprocess.run([str(ROOT / "invoke-docker.sh")], env=env, check=False)
    wall_sec = time.monotonic() - started
    artifact = ROOT / "artifacts" / run_id
    report_path = artifact / "report.json"
    report = json.loads(report_path.read_text() or "{}") if report_path.exists() else {}
    eval_path = artifact / "eval.json"
    return {
        "run_id": run_id,
        "project": project,
        "exit": completed.returncode,
        "exit_reason": report.get("exit_reason", "no_report"),
        "duration_sec": report.get("duration_sec", wall_sec),
        "wall_sec": wall_sec,
        "findings_total": report.get("findings_total") or report.get("total_findings"),
        "protocol_retries": report.get("usage", {}).get("protocol_retries", 0),
        "total_tokens": report.get("usage", {}).get("total_tokens"),
        "f1": json.loads(eval_path.read_text())["critical_tp_f1"] if eval_path.exists() else None,
    }


def evaluate_run(run: dict) -> None:
    project = run.get("project", "pygoat")
    project_id = project_id_for(project, run["run_id"])
    key = run.pop("api_key")
    subprocess.run(
        [
            "python",
            str(ROOT / "master_checks.py"),
            "--edge-db",
            str(ROOT / "runtime" / f"data-{run['run_id']}" / "shown_findings.db"),
            "--master-url",
            os.environ.get("APPSECGATE_MASTER_HOST_URL", "http://127.0.0.1:8000"),
            "--api-key",
            key,
            "--project-id",
            project_id,
            "--output",
            str(ROOT / "artifacts" / run["run_id"] / "master-checks.json"),
        ],
        check=True,
    )
    if project != "pygoat":
        return
    subprocess.run(
        [
            "python",
            str(ROOT / "eval.py"),
            str(ROOT / "artifacts" / run["run_id"] / "report.json"),
            "--ground-truth",
            str(ROOT / "repos" / "stage1_project.json"),
            "--master-checks",
            str(ROOT / "artifacts" / run["run_id"] / "master-checks.json"),
            "--output",
            str(ROOT / "artifacts" / run["run_id"] / "eval.json"),
        ],
        check=True,
    )


def main() -> None:
    keys = json.loads(os.environ.get("APPSECGATE_MASTER_API_KEYS", "{}"))
    selected = os.environ.get("BENCH_MODELS", ",".join(MODELS)).split(",")
    parallel_values = [int(value) for value in os.environ.get("BENCH_PARALLELISM", "1,2,4").split(",")]
    internal_parallel = int(os.environ.get("APPSECGATE_AGENT_INTERNAL_PARALLEL", "2"))
    num_parallel_max = int(os.environ.get("APPSECGATE_NUM_PARALLEL_MAX", "4"))
    for parallelism in parallel_values:
        if internal_parallel * parallelism > num_parallel_max:
            raise SystemExit(
                "slot budget exceeded: "
                f"internal_parallel={internal_parallel} × external={parallelism} "
                f"> verified_num_parallel_max={num_parallel_max}"
            )
    projects = [p.strip() for p in os.environ.get("BENCH_PROJECTS", "").split(",") if p.strip()]
    run_count = int(os.environ.get("BENCH_RUNS", "4"))
    output = ROOT / "artifacts" / os.environ.get("BENCH_OUTPUT", "parallel-benchmark.json")
    results = []
    for model in selected:
        for parallelism in parallel_values:
            started = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as pool:
                if projects:
                    futures = [
                        pool.submit(run_one, model, MODELS[model], parallelism, 1, keys, project)
                        for project in projects
                    ]
                else:
                    futures = [
                        pool.submit(run_one, model, MODELS[model], parallelism, index, keys)
                        for index in range(1, run_count + 1)
                    ]
                runs = [future.result() for future in futures]
            ended = time.time()
            wall_sec = ended - started
            for run in runs:
                project = run.get("project", "pygoat")
                project_id = project_id_for(project, run["run_id"])
                if run["exit"] == 0 and os.environ.get("NO_SYNC") != "1" and keys.get(project_id):
                    run["api_key"] = keys[project_id]
                    evaluate_run(run)
            durations = sorted(run["duration_sec"] for run in runs)
            p50 = durations[len(durations) // 2] if durations else None
            p95 = (
                durations[min(len(durations) - 1, int(len(durations) * 0.95))]
                if durations
                else None
            )
            results.append(
                {
                    "model": model,
                    "parallelism": parallelism,
                    "started_at": started,
                    "ended_at": ended,
                    "wall_sec": wall_sec,
                    "throughput_repositories_per_min": len(runs) * 60 / wall_sec,
                    "p50_sec": p50,
                    "p95_sec": p95,
                    "successful_runs": sum(1 for run in runs if run["exit"] == 0),
                    "total_runs": len(runs),
                    "protocol_retries": sum(run["protocol_retries"] for run in runs),
                    "runs": runs,
                    "prometheus": {
                        name: prometheus_range(query, started, ended)
                        for name, query in QUERIES.items()
                    },
                }
            )
            output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
