"""Запросы отчёта scan_project поверх shown_findings (ADR-0005 §2.5, PR-C).

Вынесены из ``ShownFindingsStore`` отдельным модулем, чтобы класс оставался
в пределах лимита строк (AGENTS.md «File Size Limits»). Функции принимают
``db``/``project_id`` явно и работают с той же таблицей ``shown_findings``.
"""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.storage.stores._time import _now


async def get_statuses(db: Any, fingerprints: list[str]) -> dict[str, str]:
    """Пред-скан статусы находок (классификация new/reaffirmed/reopened)."""
    if not fingerprints:
        return {}
    placeholders = ",".join("?" * len(fingerprints))
    rows = await db.fetchall(
        f"SELECT fingerprint, status FROM shown_findings "
        f"WHERE fingerprint IN ({placeholders})",
        fingerprints,
    )
    return {r["fingerprint"]: r["status"] for r in rows}


async def mark_shown(db: Any, fingerprints: list[str]) -> None:
    """K3: находка реально попала в ответ агенту (ADR-0005 §2.3).

    Заполняет ``first_shown_at`` (COALESCE — только при первом показе),
    ``last_shown_at`` и инкрементирует ``show_count``.
    """
    if not fingerprints:
        return
    now = _now()
    placeholders = ",".join("?" * len(fingerprints))
    await db.execute(
        f"UPDATE shown_findings SET "
        f"first_shown_at = COALESCE(first_shown_at, ?), last_shown_at = ?, "
        f"show_count = show_count + 1 "
        f"WHERE fingerprint IN ({placeholders})",
        (now, now, *fingerprints),
    )


async def list_potentially_fixed(
    db: Any,
    project_id: str,
    branch: str | None,
    *,
    limit: int = 25,
) -> tuple[list[str], int, bool]:
    """Актуальные POTENTIALLY_FIXED проекта/ветки (§2.5, К18).

    Возвращает ``(fingerprints, total, truncated)``: fingerprint'ы отсортированы
    ``severity desc → last_seen_at desc``; ``total`` — полное число находок;
    ``truncated`` — True при превышении ``limit``.
    """
    severity_order = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
    case_sql = "CASE severity " + " ".join(
        "WHEN ? THEN ?" for _ in severity_order
    ) + " END DESC, last_seen_at DESC"
    severity_params: list[Any] = []
    for sev, rank in severity_order.items():
        severity_params.extend((sev, rank))

    where_sql = "WHERE project_id = ? AND status = 'POTENTIALLY_FIXED'"
    where_params: list[Any] = [project_id]
    if branch and branch != "<unknown>":
        where_sql += " AND last_seen_branch = ?"
        where_params.append(branch)

    rows = await db.fetchall(
        f"SELECT fingerprint FROM shown_findings {where_sql} "
        f"ORDER BY {case_sql} LIMIT ?",
        [*where_params, *severity_params, limit],
    )
    total_row = await db.fetchone(
        f"SELECT COUNT(*) AS n FROM shown_findings {where_sql}",
        where_params,
    )
    total = int(total_row["n"]) if total_row else 0
    return [r["fingerprint"] for r in rows], total, total > limit
