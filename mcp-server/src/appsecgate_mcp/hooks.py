"""Hook-хендлеры AppSecGate (Фаза 1): session_start, pre_tool_use, post_tool_use.

Хуки не являются MCP-инструментами. Их вызывают конфиги агентов через
CLI-подкоманду ``appsecgate-mcp hook <name>``: JSON читается из stdin,
результат пишется в stdout. Состояние сессии передаётся явно аргументом ``state``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from appsecgate_mcp.server import (
    _WRITE_TOOLS,
    SessionState,
    _build_scan_output,
    _resolve_inside_project,
)

HOOK_NAMES: tuple[str, ...] = ("session_start", "pre_tool_use", "post_tool_use")


def extract_touched_files(
    state: SessionState, tool_name: str, tool_input: dict[str, Any] | None
) -> list[str]:
    """Извлекает пути изменённых файлов из события post_tool_use.

    Пути проверяются через _resolve_inside_project; путь вне проекта поднимает ValueError.
    """
    if not tool_input or tool_name.strip().lower() not in _WRITE_TOOLS:
        return []
    candidates: list[str] = []
    for key in ("file_path", "path", "notebook_path", "filePath"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    paths = tool_input.get("paths")
    if isinstance(paths, list):
        candidates.extend(p for p in paths if isinstance(p, str) and p)

    seen: dict[str, None] = {}
    project = Path(state.project_path).resolve()
    for path in candidates:
        resolved = _resolve_inside_project(path, state.project_path)
        seen[str(resolved.relative_to(project))] = None
    return list(seen.keys())


async def session_start(state: SessionState, project_path: str | None = None) -> dict[str, Any]:
    """Хук SessionStart: инициализирует сессию для проекта."""
    await state.initialize(project_path, force=True)
    config = state.config
    resolved = config.resolved_rules
    trivy_db = state.trivy_db

    warnings: list[str] = list(config.rules_warnings)
    if trivy_db is not None:
        for warning in trivy_db.collect_warnings():
            if warning not in warnings:
                warnings.append(warning)

    return {
        "status": "ready",
        "project_path": state.project_path,
        "data_dir": config.data_dir,
        "enabled_categories": config.enabled_scanner_categories(),
        "scanners": state.registry.names(),
        "ruleset_version": resolved.version if resolved else None,
        "ruleset_hash": resolved.ruleset_hash if resolved else None,
        "distribution_mode": resolved.distribution_mode.value if resolved else None,
        "bundles": resolved.bundles_summary() if resolved else [],
        "trivy_db": trivy_db.model_dump(mode="json") if trivy_db else None,
        "warnings": warnings,
    }


async def pre_tool_use(
    state: SessionState, tool_name: str, tool_input: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Хук PreToolUse: локально никогда не блокируем (warn-only)."""
    await state.initialize()
    will_write = tool_name.strip().lower() in _WRITE_TOOLS
    return {
        "decision": "allow",
        "reason": "local_gate_warn_only",
        "scan_pending": will_write,
        "project_path": state.project_path,
    }


async def post_tool_use(
    state: SessionState,
    tool_name: str,
    tool_input: dict[str, Any] | None = None,
    tool_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Хук PostToolUse: сканирует изменённые файлы и пробует автофикс."""
    await state.initialize()
    try:
        files = extract_touched_files(state, tool_name, tool_input)
    except ValueError as exc:
        return {"status": "error", "reason": str(exc), "files": []}
    if not files:
        return {"status": "skipped", "reason": "no file changes detected"}

    result = await state.coordinator.scan(files, mode="file")
    state.register(result)

    autofixes: list[dict[str, Any]] = []
    for finding in result.findings[:3]:
        fix_result = await state.auto_fixer.fix(finding, "patch")
        autofixes.append(fix_result.model_dump(mode="json"))

    output = await _build_scan_output(state, result)
    output["autofixes"] = autofixes
    output["files"] = files
    return output


async def run_hook(name: str, payload: dict[str, Any], state: SessionState) -> dict[str, Any]:
    """Диспетчер хуков по имени. Состояние передаётся явно и не закрывается здесь."""
    if name == "session_start":
        return await session_start(state, payload.get("project_path"))
    if name == "pre_tool_use":
        return await pre_tool_use(state, payload.get("tool_name", ""), payload.get("tool_input"))
    if name == "post_tool_use":
        return await post_tool_use(
            state,
            payload.get("tool_name", ""),
            payload.get("tool_input"),
            payload.get("tool_response"),
        )
    raise ValueError(f"unknown hook: {name}")


async def run_hook_cli(name: str, stdin_text: str, project_path: str | None = None) -> str:
    """Разбирает JSON из stdin, запускает хук с новым состоянием и возвращает JSON-строку."""
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError as exc:
        return json.dumps({"status": "error", "reason": f"invalid JSON: {exc}"})
    if not isinstance(payload, dict):
        return json.dumps({"status": "error", "reason": "payload must be a JSON object"})

    state = SessionState()
    if project_path:
        state.project_path = str(Path(project_path).resolve())
    try:
        result = await run_hook(name, payload, state)
    except Exception as exc:
        result = {"status": "error", "reason": str(exc)}
    finally:
        await state.close()
    return json.dumps(result, ensure_ascii=False, default=str)


def hook_main(argv: list[str]) -> int:
    """Точка входа подкоманды `appsecgate-mcp hook <name>`."""
    parser = argparse.ArgumentParser(prog="appsecgate-mcp hook", description="Запуск хука")
    parser.add_argument("name", choices=HOOK_NAMES)
    parser.add_argument("--project", default=None, help="Корень проекта")
    args = parser.parse_args(argv)
    output = asyncio.run(run_hook_cli(args.name, sys.stdin.read(), args.project))
    sys.stdout.write(output + "\n")
    return 0
