"""FindingIdentityStore — стабильная идентичность находки."""

from __future__ import annotations

from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores._time import _now


class FindingIdentityStore:
    """Стабильная идентичность находки (arch §4.7).

    Живёт дольше ``fingerprint``: связывает ``logical_id`` с текущим
    fingerprint. ``first_seen_at`` фиксируется при первом появлении пары
    ``(project_id, logical_id)`` и не обновляется; ``last_fingerprint`` и
    ``last_seen_at`` обновляются при каждом повторном показе.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS finding_identity (
                logical_id       TEXT NOT NULL,
                project_id       TEXT NOT NULL,
                rule_id          TEXT NOT NULL,
                file_path        TEXT NOT NULL,
                first_seen_at    TIMESTAMP NOT NULL,
                last_fingerprint TEXT NOT NULL,
                last_seen_at     TIMESTAMP NOT NULL,
                PRIMARY KEY (project_id, logical_id)
            );
            """
        )

    async def upsert(
        self,
        project_id: str,
        logical_id: str,
        rule_id: str,
        file_path: str,
        fingerprint: str,
    ) -> None:
        now = _now()
        await self.db.execute(
            """
            INSERT INTO finding_identity
                (logical_id, project_id, rule_id, file_path, first_seen_at, last_fingerprint, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, logical_id) DO UPDATE SET
                last_fingerprint = excluded.last_fingerprint,
                last_seen_at     = excluded.last_seen_at
            """,
            (logical_id, project_id, rule_id, file_path, now, fingerprint, now),
        )
