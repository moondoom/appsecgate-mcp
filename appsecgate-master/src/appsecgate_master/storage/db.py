"""Database — обёртка над sqlite3 с WAL и retry (зеркало mcp-server storage/db.py).

master — независимый деплоймент: собственный класс дублируется намеренно
(~150 строк, паттерн ADR-0005 §2.7/arch §6), чтобы не зависеть от внутренностей
mcp-server. Всё то же: WAL, busy_timeout=10s, retry на SQLITE_BUSY/LOCKED,
записи через asyncio.to_thread, соединение защищено threading.RLock.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.05  # экспоненциальный backoff: 50ms, 100ms, 200ms


class Database:
    """Обёртка над одним SQLite-файлом (WAL, retry, thread-pool записи)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def connect(self) -> None:
        with self._lock:
            self._conn = sqlite3.connect(str(self.path), timeout=10.0, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=10000")

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------------
    # Sync-примитивы (вызываются внутри asyncio.to_thread)
    # ------------------------------------------------------------------
    def _execute_locked(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        for attempt in range(RETRY_ATTEMPTS):
            try:
                return self._conn.execute(sql, params)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                if attempt == RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(RETRY_BASE_DELAY * (2**attempt))
        raise RuntimeError("unreachable")

    def _write(self, sql: str, params: Sequence[Any] = ()) -> None:
        """execute + commit атомарно под блокировкой."""
        with self._lock:
            self._execute_locked(sql, params)
            assert self._conn is not None
            self._conn.commit()

    def _write_many(self, sql: str, params_list: Sequence[Sequence[Any]]) -> None:
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database is not connected")
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    self._conn.executemany(sql, params_list)
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                        raise
                    if attempt == RETRY_ATTEMPTS - 1:
                        raise
                    time.sleep(RETRY_BASE_DELAY * (2**attempt))
            self._conn.commit()

    def _fetchone(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._execute_locked(sql, params).fetchone()

    def _fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._execute_locked(sql, params).fetchall()

    def _execute_ddl(self, sql: str) -> None:
        """Выполняет DDL без retry-обёртки (используется при инициализации)."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database is not connected")
            self._conn.execute(sql)
            self._conn.commit()

    def _execute_script(self, sql: str) -> None:
        """Выполняет многооператорный DDL (CREATE TABLE+INDEX+TRIGGER)."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database is not connected")
            # executescript делает implicit COMMIT перед выполнением — вне транзакций.
            self._conn.executescript(sql)

    # ------------------------------------------------------------------
    # Async-обёртки (основной интерфейс для store-классов)
    # ------------------------------------------------------------------
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        await asyncio.to_thread(self._write, sql, params)

    async def execute_script(self, sql: str) -> None:
        """Выполняет многооператорный DDL (CREATE TABLE+INDEX+TRIGGER)."""
        await asyncio.to_thread(self._execute_script, sql)

    async def execute_rowcount(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Выполняет запись и возвращает число затронутых строк (rowcount)."""

        def _run() -> int:
            with self._lock:
                cursor = self._execute_locked(sql, params)
                assert self._conn is not None
                self._conn.commit()
                return cursor.rowcount

        return await asyncio.to_thread(_run)

    async def execute_many(self, sql: str, params_list: Sequence[Sequence[Any]]) -> None:
        await asyncio.to_thread(self._write_many, sql, params_list)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._fetchone, sql, params)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return await asyncio.to_thread(self._fetchall, sql, params)


async def init_database(path: str | Path) -> Database:
    """Создаёт Database, коннектится и проверяет schema_version (ADR-0005 §2.7).

    Точка вызова для приложения. Store-классы создают схему после этого
    через ``init_schema()``.
    """
    from appsecgate_master.storage.migrations import ensure_schema_version

    db = Database(path)
    db.connect()
    ensure_schema_version(db)
    return db
