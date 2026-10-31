"""FixAttemptsStore — журнал попыток верификации находок."""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores._time import _now


class FixAttemptsStore:
    """Журнал попыток верификации находок (arch §4.7).

    Каждая попытка — одна ``verify_fix``/``verify_fix_batch`` запись: что
    агент заявил (``reported_status``) и что подтвердил перескан сервера
    (``verified_status``). Собственный ``attempt_num`` на ``logical_id``.
    """

    _STATUSES = ("FIXED", "NOT_FIXED", "WONT_FIX")

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS fix_attempts (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id         TEXT NOT NULL,
                logical_id         TEXT NOT NULL,
                fingerprint        TEXT NOT NULL,
                rule_id            TEXT NOT NULL,
                file_path          TEXT NOT NULL,
                attempt_num        INTEGER NOT NULL,
                reported_status    TEXT NOT NULL,
                verified_status    TEXT NOT NULL,
                note               TEXT,
                session_id         TEXT NOT NULL,
                agent_reported_at  TIMESTAMP NOT NULL,
                verified_at        TIMESTAMP NOT NULL
            );
            """
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_fix_attempts_project "
            "ON fix_attempts(project_id, logical_id)"
        )

    async def next_attempt_num(self, project_id: str, logical_id: str) -> int:
        row = await self.db.fetchone(
            "SELECT MAX(attempt_num) AS n FROM fix_attempts WHERE project_id=? AND logical_id=?",
            (project_id, logical_id),
        )
        return int(row["n"]) + 1 if row and row["n"] is not None else 1

    async def record(
        self,
        *,
        project_id: str,
        logical_id: str,
        fingerprint: str,
        rule_id: str,
        file_path: str,
        reported_status: str,
        verified_status: str,
        note: str | None,
        session_id: str,
    ) -> int:
        """Пишет запись об attempt; возвращает attempt_num (id последней записи)."""
        attempt_num = await self.next_attempt_num(project_id, logical_id)
        now = _now()
        await self.db.execute(
            """
            INSERT INTO fix_attempts
                (project_id, logical_id, fingerprint, rule_id, file_path, attempt_num,
                 reported_status, verified_status, note, session_id,
                 agent_reported_at, verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                logical_id,
                fingerprint,
                rule_id,
                file_path,
                attempt_num,
                reported_status,
                verified_status,
                note or "",
                session_id,
                now,
                now,
            ),
        )
        return attempt_num

    async def list_for(self, project_id: str, finding_id: str) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM fix_attempts WHERE project_id=? AND (fingerprint=? OR logical_id=?) "
            "ORDER BY verified_at DESC",
            (project_id, finding_id, finding_id),
        )
        return [dict(row) for row in rows]

    async def coverage(self, project_id: str) -> dict[str, int]:
        """Число уникальных ``logical_id`` с попытками и общее число уникальных находок."""
        row = await self.db.fetchone(
            "SELECT COUNT(DISTINCT logical_id) AS n FROM fix_attempts WHERE project_id=?",
            (project_id,),
        )
        attempts = int(row["n"]) if row and row["n"] is not None else 0
        # logical_id не хранится в shown_findings (ADR-0005 §2.8, К1):
        # уникальные находки считаем через finding_identity по fingerprint,
        # как в view v_verification_coverage (arch §4.7).
        total_row = await self.db.fetchone(
            """
            SELECT COUNT(DISTINCT i.logical_id) AS n
            FROM shown_findings s
            LEFT JOIN finding_identity i
                ON i.project_id = s.project_id AND i.last_fingerprint = s.fingerprint
            WHERE s.project_id = ?
            """,
            (project_id,),
        )
        total = int(total_row["n"]) if total_row and total_row["n"] is not None else 0
        return {"attempts": attempts, "total": total}
