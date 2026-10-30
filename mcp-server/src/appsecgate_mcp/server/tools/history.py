"""Тул журнала показанных находок: get_scan_history."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.session import _resolve_inside_project
from appsecgate_mcp.server.tools.common import ensure_session


def _relative_project_path(path: str, project: str) -> str:
    """Приводит путь (абсолютный или относительный) к виду от корня проекта.

    Результат всегда с прямыми слэшами и без ведущего './'. Путь вне проекта
    поднимает ValueError (см. _resolve_inside_project).
    """
    resolved = _resolve_inside_project(path, project)
    return resolved.relative_to(Path(project).resolve()).as_posix()


def _normalize_history_item(item: dict[str, Any], project: str) -> dict[str, Any] | None:
    """Приводит file_path строки журнала к виду от корня проекта.

    Возвращает None, если путь лежит вне проекта: такая строка не попадает в ответ.
    """
    raw = item.get("file_path")
    if not isinstance(raw, str) or not raw:
        return item
    try:
        rel = _relative_project_path(raw, project)
    except ValueError:
        return None
    return {**item, "file_path": rel}


@mcp.tool()
@_log_tool
async def get_scan_history(limit: int = 50, file_path: str | None = None) -> dict[str, Any]:
    """Return the shown findings log (shown_findings.db) with verification attempts.

    Paths in items are always relative to the project root. Rows with paths
    outside the project are excluded. ``latest_attempt`` — most recent
    ``fix_attempts`` entry for the finding (or ``None``).
    """
    state = await ensure_session()
    try:
        if file_path:
            rel = _relative_project_path(file_path, state.project_path)
            rows = await state.shown_store.get_by_file(rel)
        else:
            rows = await state.shown_store.get_all(limit)
    except Exception as exc:
        return {"status": "error", "reason": str(exc), "items": []}
    items = [
        n for row in rows if (n := _normalize_history_item(row, state.project_path)) is not None
    ]
    items = items[:limit]
    verified = 0
    not_fixed = 0
    wont_fix = 0
    attempts_by_id: dict[str, Any] = {}
    for item in items:
        attempts = []
        if getattr(state, "fix_attempts_store", None) is not None and state.project_id is not None:
            attempts = await state.fix_attempts_store.list_for(
                state.project_id, item["fingerprint"]
            )
        if attempts:
            attempts_by_id[item["fingerprint"]] = attempts[0]
        status = (item.get("status") or "").upper()
        if status == "FIXED":
            verified += 1
        elif status == "WONT_FIX":
            wont_fix += 1
        elif status in ("SHOWN", "NOT_FIXED"):
            not_fixed += 1
    coverage = {"attempts": 0, "total": 0}
    if getattr(state, "fix_attempts_store", None) is not None and state.project_id is not None:
        coverage = await state.fix_attempts_store.coverage(state.project_id)
    return {
        "count": len(items),
        "items": items,
        "attempts": attempts_by_id,
        "verified": verified,
        "not_fixed": not_fixed,
        "wont_fix": wont_fix,
        "coverage": coverage,
    }
