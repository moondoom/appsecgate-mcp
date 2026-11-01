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
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--max-tokens", type=int, default=500_000)
    parser.add_argument("--max-context-chars", type=int, default=120_000)
    parser.add_argument("--master-url", default=os.environ.get("APPSECGATE_MASTER_URL"))
    parser.add_argument("--api-key", default=os.environ.get("APPSECGATE_MASTER_API_KEY"))
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
        scan=args.scan,
        policy=args.policy,
        output_format=args.output_format,
        llm_url=args.llm_url,
        llm_model=args.llm_model,
        llm_api_key=args.llm_api_key,
        llm_timeout=args.llm_timeout,
        timeout=args.timeout,
        max_iterations=args.max_iterations,
        max_tokens=args.max_tokens,
        max_context_chars=args.max_context_chars,
        master_url=args.master_url,
        master_api_key=args.api_key,
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
