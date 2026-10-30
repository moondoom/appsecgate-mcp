"""ScanCacheStore — кэш результатов сканирования (scan_cache.db)."""

from __future__ import annotations

from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores._time import _now


class ScanCacheStore:
    """Кэш результатов сканирования (минимальная версия, возможно, уйдёт).

    Инвалидация по (file_hash, scanner, scanner_version, ruleset_hash).
    Пока храним только для Semgrep — остальные сканеры быстры и не кэшируются.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS scan_cache (
                file_hash TEXT NOT NULL,
                scanner TEXT NOT NULL,
                scanner_version TEXT NOT NULL,
                ruleset_hash TEXT NOT NULL,
                result_json TEXT NOT NULL,
                cached_at TIMESTAMP NOT NULL,
                PRIMARY KEY (file_hash, scanner, scanner_version, ruleset_hash)
            );
            """
        )

    async def get(
        self, file_hash: str, scanner: str, scanner_version: str, ruleset_hash: str
    ) -> str | None:
        row = await self.db.fetchone(
            """
            SELECT result_json FROM scan_cache
            WHERE file_hash = ? AND scanner = ? AND scanner_version = ? AND ruleset_hash = ?
            """,
            (file_hash, scanner, scanner_version, ruleset_hash),
        )
        return row["result_json"] if row else None

    async def put(
        self,
        file_hash: str,
        scanner: str,
        scanner_version: str,
        ruleset_hash: str,
        result_json: str,
    ) -> None:
        await self.db.execute(
            """
            INSERT OR REPLACE INTO scan_cache
                (file_hash, scanner, scanner_version, ruleset_hash, result_json, cached_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_hash, scanner, scanner_version, ruleset_hash, result_json, _now()),
        )

    async def invalidate(self, scanner: str | None = None) -> None:
        if scanner:
            await self.db.execute("DELETE FROM scan_cache WHERE scanner = ?", (scanner,))
        else:
            await self.db.execute("DELETE FROM scan_cache")
