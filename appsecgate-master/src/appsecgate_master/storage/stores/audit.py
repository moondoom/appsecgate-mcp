"""AuditLogStore — append-only журнал приёма событий (ADR-0004 §5.4).

Строгая модель: только INSERT. UPDATE/DELETE запрещены и на уровне API
(методы не существуют), и на уровне БД (BEFORE UPDATE/DELETE-триггеры).
Строки: client_event_id, project_key, fp, event_type, outcome
(accepted | duplicate | rejected:<reason>), received_at.
"""

from __future__ import annotations

from appsecgate_master.contracts.events import MasterEvent
from appsecgate_master.storage.db import Database

_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_event_id TEXT NOT NULL,
    project_key     TEXT NOT NULL,
    fp              TEXT,
    event_type      TEXT NOT NULL,
    outcome         TEXT NOT NULL,   -- accepted|duplicate|rejected:<reason>
    received_at     TEXT NOT NULL    -- UTC ISO-8601
);
CREATE INDEX IF NOT EXISTS idx_audit_project_at ON audit_log (project_key, received_at);
CREATE TRIGGER IF NOT EXISTS trg_audit_append_only_update
BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_audit_append_only_delete
BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


class AuditLogStore:
    """Append-only ``audit_log``: запись каждого факта приёма события."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def init_schema(self) -> None:
        await self.db.execute_script(_AUDIT_DDL)

    async def record(self, event: MasterEvent, outcome: str, received_at: str) -> None:
        """Записать факт приёма (единственный способ записи в audit_log)."""
        await self.db.execute(
            "INSERT INTO audit_log (client_event_id, project_key, fp, event_type, outcome,"
            " received_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.client_event_id,
                event.project_key,
                event.fp,
                event.event_type.value,
                outcome,
                received_at,
            ),
        )

    async def list(
        self,
        *,
        project_key: str | None = None,
        since: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, str | int | None]]:
        """Строки журнала (новые первыми) с необязательными фильтрами."""
        clauses: list[str] = []
        params: list[object] = []
        if project_key is not None:
            clauses.append("project_key = ?")
            params.append(project_key)
        if since is not None:
            clauses.append("received_at >= ?")
            params.append(since)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = await self.db.fetchall(
            f"SELECT id, client_event_id, project_key, fp, event_type, outcome, received_at"
            f" FROM audit_log{where} ORDER BY id DESC LIMIT ?",
            [*params, str(limit)],
        )
        return [dict(row) for row in rows]

    async def count(self) -> int:
        row = await self.db.fetchone("SELECT COUNT(*) AS n FROM audit_log")
        return int(row["n"]) if row else 0
