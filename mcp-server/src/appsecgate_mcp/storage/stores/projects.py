"""ProjectsStore — реестр известных проектов."""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores._time import _now


class ProjectsStore:
    """Реестр известных проектов (arch §4.10).

    ``first_seen_at`` фиксируется один раз, ``last_seen_at`` обновляется при
    каждом старте сессии. ``project_path`` меняться не может — ``project_id``
    выводится из физического пути, а смена пути запрещена инвариантом №6.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id    TEXT PRIMARY KEY,
                project_alias TEXT NOT NULL,
                project_path  TEXT NOT NULL,
                first_seen_at TIMESTAMP NOT NULL,
                last_seen_at  TIMESTAMP NOT NULL
            );
            """
        )

    async def upsert(self, project_id: str, project_alias: str, project_path: str) -> None:
        now = _now()
        await self.db.execute(
            """
            INSERT INTO projects (project_id, project_alias, project_path, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                project_alias = excluded.project_alias,
                project_path  = excluded.project_path,
                last_seen_at  = excluded.last_seen_at
            """,
            (project_id, project_alias, project_path, now, now),
        )

    async def get(self, project_id: str) -> dict[str, Any] | None:
        row = await self.db.fetchone("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        return dict(row) if row else None
