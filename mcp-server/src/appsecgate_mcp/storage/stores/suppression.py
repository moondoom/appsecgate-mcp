"""SuppressionStore — локальные suppression с проектной осью (arch §3.5, T7)."""

from __future__ import annotations

from appsecgate_mcp.models.finding import Finding, Suppression
from appsecgate_mcp.storage.db import Database


class SuppressionStore:
    """Локальные suppression.

    Локальный suppression НЕ подавляет CI-находку (двойной контур gates):
    здесь — только фильтрация локального показа.

    Схема несёт ``project_id`` (PK = ``(project_id, fingerprint)``, T7):
    одинаковый fingerprint в разных проектах подавляется независимо. Старая
    схема без ``project_id`` пересоздаётся (No-migration, см. AGENTS.md).
    """

    def __init__(self, db: Database, project_id: str = "") -> None:
        self.db = db
        self.project_id = project_id

    def _table_columns(self, table: str) -> set[str]:
        rows = self.db._fetchall(f"PRAGMA table_info({table})")
        return {r["name"] for r in rows}

    def init_schema(self) -> None:
        columns = self._table_columns("suppressions")
        if columns and "project_id" not in columns:
            # Старая схема (PK = fingerprint, без проектной оси) — пересоздаём.
            self.db._execute_ddl("DROP TABLE suppressions")
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS suppressions (
                project_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                reason TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'local',
                expires_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL,
                PRIMARY KEY (project_id, fingerprint)
            );
            """
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_suppression_fp ON suppressions(project_id, fingerprint)"
        )

    async def create(self, suppression: Suppression) -> None:
        await self.db.execute(
            """
            INSERT INTO suppressions (project_id, fingerprint, reason, scope, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, fingerprint) DO UPDATE SET
                reason = excluded.reason,
                scope = excluded.scope,
                expires_at = excluded.expires_at
            """,
            (
                self.project_id,
                suppression.fingerprint,
                suppression.reason,
                suppression.scope,
                suppression.expires_at,
                suppression.created_at,
            ),
        )

    async def get(self, fingerprint: str) -> Suppression | None:
        row = await self.db.fetchone(
            "SELECT * FROM suppressions WHERE project_id = ? AND fingerprint = ?",
            (self.project_id, fingerprint),
        )
        if row is None:
            return None
        return Suppression(
            fingerprint=row["fingerprint"],
            reason=row["reason"],
            scope=row["scope"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )

    async def list_all(self) -> list[Suppression]:
        rows = await self.db.fetchall(
            "SELECT * FROM suppressions WHERE project_id = ? ORDER BY created_at DESC",
            (self.project_id,),
        )
        return [
            Suppression(
                fingerprint=r["fingerprint"],
                reason=r["reason"],
                scope=r["scope"],
                expires_at=r["expires_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def delete(self, fingerprint: str) -> None:
        await self.db.execute(
            "DELETE FROM suppressions WHERE project_id = ? AND fingerprint = ?",
            (self.project_id, fingerprint),
        )

    async def is_suppressed(self, fingerprint: str) -> bool:
        suppression = await self.get(fingerprint)
        if suppression is None:
            return False
        return not suppression.is_expired()

    async def filter_active(self, findings: list[Finding]) -> list[Finding]:
        """Убирает из списка находки с активным локальным suppression."""
        result = []
        for finding in findings:
            if not await self.is_suppressed(finding.fingerprint):
                result.append(finding)
        return result
