"""SuppressionStore — локальные suppression."""

from __future__ import annotations

from appsecgate_mcp.models.finding import Finding, Suppression
from appsecgate_mcp.storage.db import Database


class SuppressionStore:
    """Локальные suppression.

    Локальный suppression НЕ подавляет CI-находку (двойной контур gates):
    здесь — только фильтрация локального показа.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS suppressions (
                fingerprint TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'local',
                expires_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL
            );
            """
        )

    async def create(self, suppression: Suppression) -> None:
        await self.db.execute(
            """
            INSERT INTO suppressions (fingerprint, reason, scope, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                reason = excluded.reason,
                scope = excluded.scope,
                expires_at = excluded.expires_at
            """,
            (
                suppression.fingerprint,
                suppression.reason,
                suppression.scope,
                suppression.expires_at,
                suppression.created_at,
            ),
        )

    async def get(self, fingerprint: str) -> Suppression | None:
        row = await self.db.fetchone(
            "SELECT * FROM suppressions WHERE fingerprint = ?", (fingerprint,)
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
        rows = await self.db.fetchall("SELECT * FROM suppressions ORDER BY created_at DESC")
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
        await self.db.execute("DELETE FROM suppressions WHERE fingerprint = ?", (fingerprint,))

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
