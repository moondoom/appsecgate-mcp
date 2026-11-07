from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from contextlib import redirect_stdout
from pathlib import Path

from appsecgate_mcp.agent.llm import LlmError
from appsecgate_mcp.agent.models import AgentConfig
from appsecgate_mcp.agent.report import format_report
from appsecgate_mcp.agent.runner import AgentError, run_agent


def _duration_seconds(value: str) -> int:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    number, unit = (value[:-1], value[-1]) if value[-1:] in units else (value, "s")
    if not number.isdigit():
        raise argparse.ArgumentTypeError("duration must be seconds or an integer with s/m/h/d/w")
    return int(number) * units[unit]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="appsecgate-mcp agent")
    parser.add_argument("--task", default="Проверить безопасность проекта")
    parser.add_argument(
        "--project", default=os.environ.get("APPSECGATE_PROJECT_PATH") or os.getcwd()
    )
    parser.add_argument("--project-id", default=os.environ.get("APPSECGATE_PROJECT_ID"))
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("APPSECGATE_DATA_DIR")
        or os.environ.get("APPSECGATE_MCP_HOME")
        or str(Path.home() / ".appsecgate-mcp"),
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--mode", choices=["ro"], default="ro")
    parser.add_argument(
        "--agent-mode",
        choices=["free", "guided"],
        default=os.environ.get("APPSECGATE_AGENT_MODE", "guided"),
    )
    parser.add_argument("--scan", choices=["full", "diff"], default="full")
    parser.add_argument("--policy", choices=["warn", "block"], default="warn")
    parser.add_argument("--output-format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--llm-url", default=os.environ.get("APPSECGATE_LLM_URL"))
    parser.add_argument("--llm-model", default=os.environ.get("APPSECGATE_LLM_MODEL"))
    parser.add_argument("--llm-api-key", default=os.environ.get("APPSECGATE_LLM_API_KEY", "local"))
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=float(os.environ.get("APPSECGATE_LLM_TIMEOUT", "120")),
    )
    parser.add_argument(
        "--llm-failure-timeout",
        type=float,
        default=float(os.environ.get("APPSECGATE_LLM_FAILURE_TIMEOUT_S", "600")),
    )
    parser.add_argument(
        "--llm-temperature",
        type=float,
        default=float(os.environ.get("APPSECGATE_LLM_TEMPERATURE", "0")),
    )
    parser.add_argument(
        "--llm-top-p",
        type=float,
        default=float(os.environ.get("APPSECGATE_LLM_TOP_P", "1")),
    )
    parser.add_argument(
        "--llm-max-tokens",
        type=int,
        default=int(os.environ.get("APPSECGATE_LLM_MAX_TOKENS", "2048")),
    )
    parser.add_argument(
        "--llm-num-ctx",
        type=int,
        default=int(os.environ.get("APPSECGATE_LLM_NUM_CTX", "32768")),
    )
    parser.add_argument(
        "--no-reuse-verdicts",
        action="store_false",
        dest="reuse_verdicts",
        default=os.environ.get("APPSECGATE_AGENT_REUSE_VERDICTS", "1") != "0",
    )
    parser.add_argument(
        "--force-reevaluate",
        action="store_true",
        default=os.environ.get("APPSECGATE_FORCE_REEVALUATE", "0") == "1",
        help="Re-judge every reuse candidate, keeping supersedes lineage (REV-1)",
    )
    parser.add_argument(
        "--reuse-ttl",
        type=_duration_seconds,
        default=os.environ.get("APPSECGATE_AGENT_REUSE_TTL", "1w"),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("APPSECGATE_AGENT_TIMEOUT", "1800")),
    )
    parser.add_argument(
        "--internal-parallel",
        type=int,
        default=int(os.environ.get("APPSECGATE_AGENT_INTERNAL_PARALLEL", "2")),
    )
    parser.add_argument(
        "--batch-sort",
        choices=["mode_major", "none"],
        default=os.environ.get("APPSECGATE_AGENT_BATCH_SORT", "mode_major"),
    )
    parser.add_argument(
        "--mode-batch-sizes",
        type=json.loads,
        default=json.loads(os.environ.get("APPSECGATE_MODE_BATCH_SIZES") or "{}"),
        help='per-mode batch size overrides, JSON: {"cve": 16}',
    )
    parser.add_argument(
        "--adaptive-max-tokens",
        action="store_true",
        default=os.environ.get("APPSECGATE_ADAPTIVE_MAX_TOKENS") == "1",
    )
    parser.add_argument(
        "--mode-b",
        action="store_true",
        default=os.environ.get("APPSECGATE_MODE_B") == "1",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=int(os.environ.get("APPSECGATE_AGENT_MAX_ITERATIONS", "50")),
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=int(os.environ.get("APPSECGATE_AGENT_MAX_RESTARTS", "3")),
    )
    parser.add_argument(
        "--max-compactions",
        type=int,
        default=int(os.environ.get("APPSECGATE_AGENT_MAX_COMPACTIONS", "5")),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("APPSECGATE_AGENT_MAX_TOKENS", "500000")),
    )
    parser.add_argument(
        "--max-context-chars",
        type=int,
        default=int(os.environ.get("APPSECGATE_AGENT_MAX_CONTEXT_CHARS", "120000")),
    )
    parser.add_argument("--master-url", default=os.environ.get("APPSECGATE_MASTER_URL"))
    parser.add_argument("--api-key", default=os.environ.get("APPSECGATE_MASTER_API_KEY"))
    parser.add_argument("--knowledge-cutoff", default=os.environ.get("APPSECGATE_KNOWLEDGE_CUTOFF"))
    parser.add_argument(
        "--no-master-knowledge",
        action="store_true",
        default=os.environ.get("APPSECGATE_NO_MASTER_KNOWLEDGE") == "1",
    )
    parser.add_argument("--no-sync", action="store_true")
    return parser


def _sync(config: AgentConfig) -> int:
    if config.no_sync or not config.master_url:
        return 0
    from appsecgate_mcp.sync.cli import sync_main

    argv = [
        "--data-dir",
        str(config.data_dir),
        "--master-url",
        config.master_url,
        "--api-key",
        config.master_api_key or "",
    ]
    if config.project_id:
        argv += ["--project-id", config.project_id]
    with redirect_stdout(sys.stderr):
        return sync_main(argv)


def _error(config: AgentConfig, started: float, reason: str, message: str) -> None:
    report = {
        "run_id": config.run_id,
        "mode": config.mode,
        "model": config.llm_model,
        "exit_reason": reason,
        "error": message,
        "duration_sec": round(time.monotonic() - started, 3),
    }
    if config.output_format == "json":
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"appsecgate agent: error: {message}", file=sys.stderr)


def _contains_llm_error(exc: BaseException) -> bool:
    if isinstance(exc, LlmError):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_contains_llm_error(item) for item in exc.exceptions)
    return False


def _error_message(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(_error_message(item) for item in exc.exceptions)
    return str(exc)


def agent_main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.llm_url or not args.llm_model:
        print("appsecgate agent: error: --llm-url and --llm-model are required", file=sys.stderr)
        return 2
    config = AgentConfig(
        project=Path(args.project),
        project_id=args.project_id,
        data_dir=Path(args.data_dir),
        run_id=args.run_id or uuid.uuid4().hex,
        mode=args.mode,
        agent_mode=args.agent_mode,
        scan=args.scan,
        policy=args.policy,
        output_format=args.output_format,
        llm_url=args.llm_url,
        llm_model=args.llm_model,
        llm_api_key=args.llm_api_key,
        llm_timeout=args.llm_timeout,
        llm_failure_timeout=args.llm_failure_timeout,
        llm_temperature=args.llm_temperature,
        llm_top_p=args.llm_top_p,
        llm_max_tokens=args.llm_max_tokens,
        llm_num_ctx=args.llm_num_ctx,
        internal_parallel=args.internal_parallel,
        batch_sort=args.batch_sort,
        mode_batch_sizes=args.mode_batch_sizes,
        adaptive_max_tokens=args.adaptive_max_tokens,
        mode_b=args.mode_b,
        reuse_verdicts=args.reuse_verdicts,
        force_reevaluate=args.force_reevaluate,
        reuse_ttl_seconds=args.reuse_ttl,
        timeout=args.timeout,
        max_iterations=args.max_iterations,
        max_restarts=args.max_restarts,
        max_compactions=args.max_compactions,
        max_tokens=args.max_tokens,
        max_context_chars=args.max_context_chars,
        master_url=args.master_url,
        master_api_key=args.api_key,
        knowledge_cutoff=args.knowledge_cutoff or None,
        no_master_knowledge=args.no_master_knowledge,
        no_sync=args.no_sync,
    )
    started = time.monotonic()
    try:
        report = asyncio.run(asyncio.wait_for(run_agent(config), timeout=config.timeout))
        sync_code = _sync(config)
        report["action_log"].append({"tool": "sync", "status": "ok" if sync_code == 0 else "error"})
        if sync_code != 0:
            raise AgentError(f"sync failed with exit code {sync_code}")
    except TimeoutError:
        _error(config, started, "timeout", f"agent exceeded timeout={config.timeout}s")
        return 2
    except Exception as exc:
        reason = "llm_error" if _contains_llm_error(exc) else "infrastructure_error"
        _error(config, started, reason, _error_message(exc))
        return 2
    print(format_report(report, config.output_format))
    return 0
