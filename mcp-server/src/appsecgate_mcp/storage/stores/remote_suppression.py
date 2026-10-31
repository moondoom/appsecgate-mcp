"""RemoteSuppressionStore — CI/global suppressions, скачанные с master (MS-5)."""

from __future__ import annotations

from appsecgate_mcp.models.finding import Finding, Suppression
from appsecgate_mcp.storage.db import Database


class RemoteSuppressionStore:
    """Отдельный remote-слой: не смешивается с локальными suppressions."""

    def __init__(self, db: Database, project_id: str) -> None:
        self.db = db
        self.project_id = project_id

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS remote_suppressions (
                project_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                reason TEXT NOT NULL,
                scope TEXT NOT NULL,
                expires_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL,
                PRIMARY KEY (project_id, fingerprint)
            );
            """
        )

    async def replace_all(self, suppressions: list[Suppression]) -> None:
        """Атомарно заменить remote-набор только текущего проекта."""
        operations: list[tuple[str, tuple[object, ...]]] = [
            ("DELETE FROM remote_suppressions WHERE project_id = ?", (self.project_id,))
        ]
        operations.extend(
            (
                """
                INSERT INTO remote_suppressions
                    (project_id, fingerprint, reason, scope, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    self.project_id,
                    item.fingerprint,
                    item.reason,
                    item.scope,
                    item.expires_at,
                    item.created_at,
                ),
            )
            for item in suppressions
        )
        await self.db.execute_transaction(operations)

    async def get(self, fingerprint: str) -> Suppression | None:
        row = await self.db.fetchone(
            "SELECT * FROM remote_suppressions WHERE project_id = ? AND fingerprint = ?",
            (self.project_id, fingerprint),
        )
        return _row_to_suppression(row) if row is not None else None

    async def list_all(self) -> list[Suppression]:
        rows = await self.db.fetchall(
            "SELECT * FROM remote_suppressions WHERE project_id = ? ORDER BY fingerprint",
            (self.project_id,),
        )
        return [_row_to_suppression(row) for row in rows]

    async def is_suppressed(self, fingerprint: str) -> bool:
        suppression = await self.get(fingerprint)
        return suppression is not None and not suppression.is_expired()

    async def filter_active(self, findings: list[Finding]) -> list[Finding]:
        result = []
        for finding in findings:
            if not await self.is_suppressed(finding.fingerprint):
                result.append(finding)
        return result


def _row_to_suppression(row) -> Suppression:
    return Suppression(
        fingerprint=row["fingerprint"],
        reason=row["reason"],
        scope=row["scope"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
    )
