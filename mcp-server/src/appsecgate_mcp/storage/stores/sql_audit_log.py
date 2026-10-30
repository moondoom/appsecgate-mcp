"""SqlAuditLogStore — журнал SQL-запросов ``query_findings_db``."""

from __future__ import annotations

from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores._time import _now


class SqlAuditLogStore:
    """Журнал SQL-запросов ``query_findings_db`` (arch §4.7, требование F19).

    Хранит только текст запроса и метаданные. Запросы ограничены views и не
    могут содержать секретов (все значения в БД уже redacted), поэтому сам
    SQL логировать безопасно (инвариант №4 / §6 NF11).
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS sql_audit_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id    TEXT NOT NULL,
                session_id    TEXT NOT NULL,
                sql           TEXT NOT NULL,
                duration_ms   INTEGER,
                row_count     INTEGER,
                executed_at   TIMESTAMP NOT NULL
            );
            """
        )

    async def record(
        self,
        project_id: str,
        session_id: str,
        sql: str,
        duration_ms: int,
        row_count: int,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO sql_audit_log
                (project_id, session_id, sql, duration_ms, row_count, executed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, session_id, sql, duration_ms, row_count, _now()),
        )
