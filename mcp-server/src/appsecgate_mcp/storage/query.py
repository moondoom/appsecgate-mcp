"""Read-only SQL-запросы к findings (arch §4.4, требование F4).

Гарантии:
  * отдельное соединение ``file:...?mode=ro`` (URIs, read-only на уровне SQLite);
  * authorizer пропускает только ``SELECT``/``READ``/``FUNCTION`` — любые
    ``UPDATE``/``DELETE``/``INSERT``/``ATTACH``/``PRAGMA``/``CREATE``
    отклоняются на C-уровне, а не только по regexp;
  * только публичные views (§4.7);
  * автоматический ``LIMIT 1000`` и автофильтр ``project_id``;
  * один statement (запрет ``;``).

Пишет в ``sql_audit_log`` вызывающая сторона (tool-обёртка в server.py).
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from appsecgate_mcp.storage.db import Database

# Публичные views (arch §4.7). v_attempts / v_verification_coverage добавляются
# на этапе верификации (arch §8.3), когда появляется таблица fix_attempts.
# Помимо актуальных имён allowlist содержит версионированные снапшоты ``_v1``
# (arch F13): схема меняется — новый ``_vN``, старый живёт минимум 2 релиза.
PUBLIC_VIEWS: tuple[str, ...] = (
    "v_findings",
    "v_attempts",
    "v_summary",
    "v_verification_coverage",
    "v_projects",
    "v_findings_v1",
    "v_attempts_v1",
    "v_summary_v1",
    "v_verification_coverage_v1",
    "v_projects_v1",
)

_MAX_ROWS = 1000

_SELECT_RE = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
_FORBIDDEN_RE = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|CREATE|DROP|ALTER|INSERT|UPDATE|DELETE|"
    r"REPLACE|VACUUM|REINDEX|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|TRANSACTION)\b",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\b", re.IGNORECASE)
_TABLE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Ключевые слова, после которых список таблиц во FROM/JOIN гарантированно
# заканчивается — их учитываем при извлечении имён через запятую.
_CLAUSE_STOP_RE = re.compile(
    r"\b(WHERE|GROUP\s+BY|ORDER\s+BY|LIMIT|HAVING|ON|USING)\b", re.IGNORECASE
)
# Начало хвостовых клауз после предиката: всё, что идёт ПОСЛЕ WHERE.
_TAIL_RE = re.compile(r"\b(GROUP\s+BY|ORDER\s+BY|LIMIT|HAVING)\b", re.IGNORECASE)


class ReadOnlyQueryError(Exception):
    """Запрос отклонён политикой read-only (не является ошибкой сервера)."""


def _validate(sql: str) -> None:
    """Проверяет, что запрос — одиночный SELECT только по публичным views."""
    if not sql or not sql.strip():
        raise ReadOnlyQueryError("empty SQL")
    if ";" in sql:
        raise ReadOnlyQueryError("only a single statement is allowed (no ';')")
    if not _SELECT_RE.match(sql):
        raise ReadOnlyQueryError("only SELECT statements are allowed")
    if _FORBIDDEN_RE.search(sql):
        raise ReadOnlyQueryError("statement contains a forbidden keyword")
    tables = _extract_tables(sql)
    if not tables:
        raise ReadOnlyQueryError("no FROM/JOIN clause found (views only)")
    allowed = {name.lower() for name in PUBLIC_VIEWS}
    for table in tables:
        if table.lower() not in allowed:
            raise ReadOnlyQueryError(
                f"table '{table}' is not an allowed view; allowed: {', '.join(PUBLIC_VIEWS)}"
            )


def _extract_tables(sql: str) -> list[str]:
    """Извлекает имена таблиц из FROM/JOIN, включая списки через запятую.

    Подзапросы (``FROM (SELECT ...)``) отклоняются: их содержимое проверять
    в одиночном SELECT нельзя, поэтому политика «только публичные views»
    их не допускает.
    """
    tables: list[str] = []
    for kw in _TABLE_RE.finditer(sql):
        tail = sql[kw.end() :]
        tail_stripped = tail.lstrip()
        # FROM/JOIN с подзапросом: `FROM (` / `JOIN (`.
        if tail_stripped.startswith("("):
            raise ReadOnlyQueryError("subqueries in FROM/JOIN are not allowed (views only)")
        m = _TABLE_NAME_RE.match(tail_stripped)
        if not m:
            continue
        tables.append(m.group(0))
        # Разбираем список через запятую, останавливаясь на ключевых словах.
        rest = tail_stripped[m.end() :]
        pos = _CLAUSE_STOP_RE.search(rest)
        head = rest if pos is None else rest[: pos.start()]
        for part in head.split(","):
            part = part.strip()
            pm = _TABLE_NAME_RE.match(part)
            if pm:
                tables.append(pm.group(0))
    return tables


def _finalize(sql: str, project_id: str) -> str:
    """Добавляет автофильтр ``project_id`` и ``LIMIT 1000`` (если нет)."""
    result = sql.strip().rstrip(";")
    # project_id — sha256-hexdigest[:16], безопасен для инъекции как literal.
    literal = f"'{project_id}'"
    where = re.search(r"\bWHERE\b", result, re.IGNORECASE)
    if where:
        # Хвост после предиката WHERE: GROUP BY / ORDER BY / LIMIT / HAVING
        # остаётся СНАРУЖИ скобок, иначе скобка закрывается слишком поздно и
        # SQLite падает с синтаксической ошибкой.
        tail = _TAIL_RE.search(result, where.end())
        if tail:
            predicate = result[where.end() : tail.start()].strip()
            result = (
                result[: where.end()]
                + f" project_id = {literal} AND ({predicate})"
                + " "
                + result[tail.start() :].lstrip()
            )
        else:
            # Пользовательский WHERE оборачиваем в скобки: `AND` приоритетнее
            # `OR`, иначе автофильтр project_id ослабляется в `a OR b`.
            result = (
                result[: where.end()]
                + f" project_id = {literal} AND ("
                + result[where.end() :].lstrip()
                + ")"
            )
    else:
        tail = _TAIL_RE.search(result)
        if tail:
            result = (
                result[: tail.start()] + f" WHERE project_id = {literal} " + result[tail.start() :]
            )
        else:
            result += f" WHERE project_id = {literal}"
    if not _LIMIT_RE.search(result):
        result += " LIMIT 1000"
    return result


def _authorizer(action: int, *_args: Any) -> int:
    """Разрешает только чтение; всё остальное отклоняется на уровне SQLite."""
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def init_views(db: Database) -> None:
    """Создаёт публичные views (arch §4.7; версионирование см. §7.2 F13)."""
    db._execute_ddl(
        """
        CREATE VIEW IF NOT EXISTS v_projects AS
        SELECT project_id, project_alias, project_path, first_seen_at, last_seen_at
        FROM projects
        """
    )
    db._execute_ddl(
        """
        CREATE VIEW IF NOT EXISTS v_findings AS
        SELECT
            s.project_id,
            s.fingerprint,
            s.logical_id,
            s.rule_id,
            s.file_path,
            s.severity,
            s.scanner,
            s.status,
            s.first_shown_at,
            s.last_shown_at,
            s.show_count,
            i.first_seen_at,
            c.snippet,
            c.message,
            c.remediation
        FROM shown_findings s
        LEFT JOIN finding_identity i
            ON i.project_id = s.project_id AND i.logical_id = s.logical_id
        LEFT JOIN finding_context c
            ON c.project_id = s.project_id AND c.fingerprint = s.fingerprint
        """
    )
    db._execute_ddl(
        """
        CREATE VIEW IF NOT EXISTS v_summary AS
        SELECT
            project_id,
            severity,
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'SHOWN' THEN 1 ELSE 0 END) AS shown,
            SUM(CASE WHEN status = 'FIXED' THEN 1 ELSE 0 END) AS fixed,
            SUM(CASE WHEN status = 'SUPPRESSED' THEN 1 ELSE 0 END) AS suppressed
        FROM shown_findings
        GROUP BY project_id, severity
        """
    )
    db._execute_ddl(
        """
        CREATE VIEW IF NOT EXISTS v_attempts AS
        SELECT
            project_id,
            logical_id,
            fingerprint,
            rule_id,
            file_path,
            attempt_num,
            reported_status,
            verified_status,
            note,
            session_id,
            agent_reported_at,
            verified_at
        FROM fix_attempts
        """
    )
    db._execute_ddl(
        """
        CREATE VIEW IF NOT EXISTS v_verification_coverage AS
        SELECT
            s.project_id,
            COUNT(DISTINCT s.logical_id) AS total_findings,
            COUNT(DISTINCT a.logical_id) AS attempted_findings,
            CASE WHEN COUNT(DISTINCT s.logical_id) = 0 THEN 0
                 ELSE ROUND(100.0 * COUNT(DISTINCT a.logical_id) / COUNT(DISTINCT s.logical_id), 2)
            END AS coverage_pct
        FROM shown_findings s
        LEFT JOIN (
            SELECT DISTINCT project_id, logical_id FROM fix_attempts
        ) a ON a.project_id = s.project_id AND a.logical_id = s.logical_id
        GROUP BY s.project_id
        """
    )
    # Версионированные снапшоты views (arch §4.7, F13): каждое изменение схемы
    # view рождает новый ``_vN``; предыдущая версия живёт минимум 2 релиза.
    # Здесь фиксируем текущую (``_v1``) как baseline для будущих ``_v2``.
    for _name in ("v_findings", "v_attempts", "v_summary", "v_verification_coverage", "v_projects"):
        db._execute_ddl(f"CREATE VIEW IF NOT EXISTS {_name}_v1 AS SELECT * FROM {_name}")


def run_query(
    db_path: str | Path,
    sql: str,
    params: list[Any] | tuple[Any, ...] | None,
    project_id: str,
) -> dict[str, Any]:
    """Проверяет и выполняет read-only SELECT. Возвращает ``{rows, row_count, sql}``."""
    _validate(sql)
    finalized = _finalize(sql, project_id)

    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.set_authorizer(_authorizer)
    try:
        started = time.perf_counter()
        cursor = conn.execute(finalized, tuple(params or ()))
        rows = [dict(row) for row in cursor.fetchall()]
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
    finally:
        conn.close()

    return {"rows": rows, "row_count": len(rows), "sql": finalized, "duration_ms": duration_ms}
