from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from appsecgate_master.storage.db import Database

_VIEWS = {"v_triage_verdicts", "v_triage_knowledge", "v_cve", "v_cve_affected"}
_FORBIDDEN = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|CREATE|DROP|ALTER|INSERT|UPDATE|DELETE|REPLACE|"
    r"VACUUM|REINDEX|BEGIN|COMMIT|ROLLBACK|SAVEPOINT)\b",
    re.IGNORECASE,
)
_LIMIT = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_TAIL = re.compile(r"\b(GROUP\s+BY|ORDER\s+BY|LIMIT|HAVING)\b", re.IGNORECASE)
_TABLE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_SAFE_PROJECT = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SAFE_CUTOFF = re.compile(r"^[0-9T:+.Z-]+$")


def _validate(sql: str) -> set[str]:
    if not sql.strip().lower().startswith("select") or ";" in sql:
        raise ValueError("only one SELECT statement is allowed")
    if _FORBIDDEN.search(sql):
        raise ValueError("statement contains a forbidden keyword")
    views = {item.lower() for item in _TABLE.findall(sql)}
    if not views or not views.issubset(_VIEWS):
        raise ValueError("only whitelisted knowledge views are allowed")
    if re.search(r"\b(?:FROM|JOIN)\s*\(", sql, re.IGNORECASE):
        raise ValueError("subqueries are not allowed")
    return views


def _finalize(sql: str, views: set[str], project: str, cutoff: str | None) -> str:
    if not _SAFE_PROJECT.fullmatch(project):
        raise ValueError("invalid project key")
    if cutoff is not None and not _SAFE_CUTOFF.fullmatch(cutoff):
        raise ValueError("invalid knowledge cutoff")
    conditions: list[str] = []
    if "v_triage_verdicts" in views:
        conditions.append(f"project_key = '{project}'")
    if cutoff and views.intersection({"v_triage_verdicts", "v_triage_knowledge"}):
        conditions.append(f"at <= '{cutoff}'")
    result = sql.strip()
    if conditions:
        predicate = " AND ".join(conditions)
        where = re.search(r"\bWHERE\b", result, re.IGNORECASE)
        tail = _TAIL.search(result, where.end() if where else 0)
        if where:
            end = tail.start() if tail else len(result)
            existing = result[where.end() : end].strip()
            result = f"{result[: where.end()]} {predicate} AND ({existing}) {result[end:]}"
        else:
            end = tail.start() if tail else len(result)
            result = f"{result[:end]} WHERE {predicate} {result[end:]}"
    if not _LIMIT.search(result):
        result += " LIMIT 1000"
    return result


def _authorizer(action: int, *_args: Any) -> int:
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


async def run_query(
    db: Database, sql: str, params: list[Any] | None, project: str, cutoff: str | None
) -> dict[str, Any]:
    views = _validate(sql)
    finalized = _finalize(sql, views, project, cutoff)
    if getattr(db, "is_postgres", False):
        async with db.transaction():
            await db.execute("SET TRANSACTION READ ONLY")
            rows = [dict(row) for row in await db.fetchall(finalized, tuple(params or ()))]
    else:
        uri = f"file:{Path(db.path).resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.set_authorizer(_authorizer)
        try:
            rows = [
                dict(row) for row in connection.execute(finalized, tuple(params or ())).fetchall()
            ]
        finally:
            connection.close()
    return {"status": "ok", "rows": rows, "row_count": len(rows), "sql": finalized}
