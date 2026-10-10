"""Database — легковесная обёртка над sqlite3 с RETRY и WAL.

Причины собственной обёртки вместо ORM:
  - минимум зависимостей (sqlite3 из stdlib);
  - предсказуемое поведение в контейнере с read-only rootfs;
  - explicit retry на SQLITE_BUSY/LOCKED (arch §6).

Все записи производятся в потоке через `asyncio.to_thread` — вызывающая
сторона остаётся async. Соединение открывается с `check_same_thread=False`
и защищено `threading.RLock`, т.к. `asyncio.to_thread` использует пул
потоков и один и тот же `_conn` попадает в разные потоки.
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
    """Обёртка над одним SQLite-файлом.

    Включает WAL-режим и busy_timeout, пишет через background thread pool.
    """

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

    # ------------------------------------------------------------------
    # Async-обёртки (основной интерфейс для store-классов)
    # ------------------------------------------------------------------
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        await asyncio.to_thread(self._write, sql, params)

    async def execute_many(self, sql: str, params_list: Sequence[Sequence[Any]]) -> None:
        await asyncio.to_thread(self._write_many, sql, params_list)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._fetchone, sql, params)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return await asyncio.to_thread(self._fetchall, sql, params)


async def init_databases(paths: dict[str, Path]) -> dict[str, Database]:
    """Создаёт и инициализирует все базы (schema — в setters каждого store)."""
    databases: dict[str, Database] = {}
    for name, path in paths.items():
        db = Database(path)
        db.connect()
        databases[name] = db
    return databases
