"""Регрессионные тесты storage-слоя: thread-safety SQLite.

Воспроизводит баг из `get_scan_history`: соединение открывается в одном
потоке, а `asyncio.to_thread` исполняет запросы в разных потоках пула.
Без `check_same_thread=False` + блокировки это падает с
"SQLite objects created in a thread can only be used in that same thread".
"""

from __future__ import annotations

import asyncio

import pytest

from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores import ShownFindingsStore

pytestmark = pytest.mark.asyncio


def _make_finding(fp: str) -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="test.rule",
        severity=Severity.HIGH,
        file_path="app.py",
        scanner="semgrep",
        category=Category.SAST,
    )


async def test_writes_and_reads_across_thread_pool(tmp_path):
    """Запись/чтение через to_thread из разных потоков не должна падать."""
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = ShownFindingsStore(db)
    store.init_schema()

    # Параллельные записи → разные потоки default-экзекьютора.
    await asyncio.gather(*[store.record_shown(_make_finding(f"fp-{i}")) for i in range(20)])

    rows = await store.get_all(limit=100)
    assert len(rows) == 20
    assert {r["fingerprint"] for r in rows} == {f"fp-{i}" for i in range(20)}

    db.close()


async def test_history_query_does_not_raise(tmp_path):
    """Прямая проверка сценария get_scan_history (пустая БД)."""
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = ShownFindingsStore(db)
    store.init_schema()

    rows = await store.get_all(limit=10)  # раньше падало с cross-thread
    assert rows == []

    db.close()
