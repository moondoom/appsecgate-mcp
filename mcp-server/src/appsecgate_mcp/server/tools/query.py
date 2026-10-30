"""Тулы запросов к БД и экспорта: query_findings_db, export_snapshot."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.tools.common import ensure_session
from appsecgate_mcp.server.tools.config import _atomic_write
from appsecgate_mcp.storage.query import ReadOnlyQueryError, run_query


@mcp.tool()
@_log_tool
async def query_findings_db(sql: str, params: list[Any] | None = None) -> dict[str, Any]:
    """Read-only SELECT on public views (v_findings, v_summary, v_projects).

    Project filter (project_id) and LIMIT 1000 are added by the server
    automatically — do not specify them in SQL. WHERE/GROUP BY/ORDER BY/HAVING
    are allowed, e.g. "SELECT severity, COUNT(*) AS n FROM v_findings
    WHERE status = 'SHOWN' GROUP BY severity".
    """
    state = await ensure_session()
    if state.project_id is None or "shown" not in state.databases:
        return {"status": "error", "reason": "session not initialized"}
    db_path = state.databases["shown"].path
    try:
        result = await asyncio.to_thread(run_query, db_path, sql, params, state.project_id)
    except ReadOnlyQueryError as exc:
        return {"status": "error", "reason": str(exc)}
    except sqlite3.Error as exc:
        return {"status": "error", "reason": f"sql error: {exc}"}

    # Каждый запрос — в sql_audit_log (arch §4.4, требование F19).
    if state.sql_audit_store is not None:
        try:
            await state.sql_audit_store.record(
                state.project_id,
                state.session_id,
                result["sql"],
                int(result["duration_ms"]),
                result["row_count"],
            )
        except Exception:
            pass

    return {
        "status": "ok",
        "rows": result["rows"],
        "row_count": result["row_count"],
        "sql": result["sql"],
    }


@mcp.tool()
@_log_tool
async def export_snapshot(
    path: str, format: str = "ndjson", project_id: str | None = None
) -> dict[str, Any]:
    """Export a snapshot of findings in ndjson format (parquet — Phase 2)."""
    state = await ensure_session()
    if format == "parquet":
        return {
            "status": "error",
            "reason": (
                "parquet export is not available in Phase 1 "
                "(no new production dependencies); use format='ndjson'"
            ),
        }
    if format != "ndjson":
        return {"status": "error", "reason": f"unsupported format: {format}"}
    if state.project_id is None or "shown" not in state.databases:
        return {"status": "error", "reason": "session not initialized"}

    pid = project_id or state.project_id
    db_path = state.databases["shown"].path
    try:
        result = await asyncio.to_thread(
            run_query, db_path, "SELECT * FROM v_findings LIMIT 100000", None, pid
        )
    except (ReadOnlyQueryError, sqlite3.Error) as exc:
        return {"status": "error", "reason": str(exc)}

    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"status": "error", "reason": f"cannot create directory: {exc}"}

    text = "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in result["rows"])
    if text:
        text += "\n"
    try:
        _atomic_write(target, text)
    except OSError as exc:
        return {"status": "error", "reason": f"cannot write snapshot: {exc}"}

    return {
        "status": "ok",
        "path": str(target),
        "format": "ndjson",
        "rows": result["row_count"],
    }
