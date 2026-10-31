"""Запросы/переходы negative-merge поверх shown_findings (ADR-0005 §2.1–2.4).

Вынесены из ``ShownFindingsStore`` отдельным модулем, чтобы класс оставался
в лимите размера файла (AGENTS.md «File Size Limits»; прецедент —
``shown_report.py``). Положительный merge живёт в ``record_shown_batch``.
"""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores._time import _now


async def get_negative_candidates(
    db: Database,
    project_id: str,
    file_paths: list[str] | None = None,
    branch: str | None = None,
) -> list[dict[str, Any]]:
    """Кандидаты на negative-merge в охвате тула (branch-фильтр §2.4, К10).

    ``file_paths=None`` — глобальный охват (scan_project, §2.1): все находки
    проекта/ветки, файловый фильтр не применяется.
    """
    sql = (
        "SELECT fingerprint, status, missed_scan_count, file_path "
        "FROM shown_findings WHERE project_id = ?"
    )
    params: list[Any] = [project_id]
    if file_paths:
        placeholders = ",".join("?" * len(file_paths))
        sql += f" AND file_path IN ({placeholders})"
        params.extend(file_paths)
    if branch and branch != "<unknown>":
        sql += " AND last_seen_branch = ?"
        params.append(branch)
    sql += " ORDER BY fingerprint"
    rows = await db.fetchall(sql, params)
    return [dict(r) for r in rows]


async def mark_missing(db: Database, updates: list[tuple[str, str, int]]) -> None:
    """Применяет negative-merge переходы; не трогает терминальные статусы (К7)."""
    now = _now()
    await db.execute_many(
        "UPDATE shown_findings SET status = ?, missed_scan_count = ?, status_updated_at = ? "
        "WHERE fingerprint = ? AND status IN ('SHOWN', 'POTENTIALLY_FIXED', 'REOPENED')",
        [(status, missed, now, fp) for fp, status, missed in updates],
    )
