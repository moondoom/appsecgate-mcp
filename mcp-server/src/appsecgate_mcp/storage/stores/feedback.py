"""FeedbackStore — обратная связь разработчика (feedback.db)."""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores._time import _now


class FeedbackStore:
    """Обратная связь разработчика — офлайн-очередь для master (Фаза 2)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                feedback_type TEXT NOT NULL,  -- FALSE_POSITIVE | CONFIRMED | WONT_FIX
                reason TEXT,
                created_at TIMESTAMP NOT NULL,
                synced_at TIMESTAMP
            );
            """
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_feedback_fingerprint ON feedback(fingerprint)"
        )

    async def save(self, fingerprint: str, feedback_type: str, reason: str | None = None) -> int:
        normalized = feedback_type.strip().upper()
        if normalized not in ("FALSE_POSITIVE", "CONFIRMED", "WONT_FIX"):
            raise ValueError(f"Invalid feedback_type: {feedback_type}")
        await self.db.execute(
            "INSERT INTO feedback (fingerprint, feedback_type, reason, created_at) VALUES (?, ?, ?, ?)",
            (fingerprint, normalized, reason or "", _now()),
        )
        row = await self.db.fetchone("SELECT last_insert_rowid() AS id")
        return int(row["id"]) if row else -1

    async def get_for(self, fingerprint: str) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM feedback WHERE fingerprint = ? ORDER BY created_at DESC",
            (fingerprint,),
        )
        return [dict(row) for row in rows]

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    async def delete(self, feedback_id: int) -> None:
        await self.db.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
