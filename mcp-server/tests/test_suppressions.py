"""Тесты T7: suppression-скоп привязан к project_id.

Одинаковый fingerprint в разных проектах подавляется независимо; старая
схема (PK = fingerprint без project_id) пересоздаётся (No-migration).
"""

from __future__ import annotations

from appsecgate_mcp.models.finding import Category, Finding, Severity, Suppression
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores import SuppressionStore


def _finding(fp: str) -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="test.rule",
        severity=Severity.HIGH,
        file_path="a.py",
        scanner="semgrep",
        category=Category.SAST,
    )


async def test_suppressions_isolated_by_project_id(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    s1 = SuppressionStore(db, "p1")
    s1.init_schema()
    s2 = SuppressionStore(db, "p2")

    await s1.create(Suppression(fingerprint="fp-1", reason="known fp"))
    assert await s1.is_suppressed("fp-1") is True
    # Тот же fingerprint в другом проекте — не подавлен.
    assert await s2.is_suppressed("fp-1") is False
    assert await s2.get("fp-1") is None

    # filter_active скрывает находку только в p1.
    findings = [_finding("fp-1")]
    assert await s1.filter_active(findings) == []
    assert await s2.filter_active(findings) == findings

    # delete изолирован по проекту.
    await s2.delete("fp-1")
    assert await s1.is_suppressed("fp-1") is True
    await s1.delete("fp-1")
    assert await s1.is_suppressed("fp-1") is False
    db.close()


async def test_suppressions_same_fingerprint_both_projects(tmp_path):
    """Один и тот же fingerprint можно подавить независимо в двух проектах."""
    db = Database(tmp_path / "shown.db")
    db.connect()
    s1 = SuppressionStore(db, "p1")
    s1.init_schema()
    s2 = SuppressionStore(db, "p2")

    await s1.create(Suppression(fingerprint="fp-1", reason="a"))
    await s2.create(Suppression(fingerprint="fp-1", reason="b"))

    assert (await s1.get("fp-1")).reason == "a"
    assert (await s2.get("fp-1")).reason == "b"
    assert len(await s1.list_all()) == 1
    assert len(await s2.list_all()) == 1
    db.close()


async def test_suppressions_recreates_old_schema(tmp_path):
    """Старая таблица без project_id пересоздаётся (No-migration)."""
    db = Database(tmp_path / "shown.db")
    db.connect()
    db._execute_ddl(
        """
        CREATE TABLE suppressions (
            fingerprint TEXT PRIMARY KEY,
            reason TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'local',
            expires_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL
        );
        """
    )
    SuppressionStore(db, "p1").init_schema()

    cols = {r["name"] for r in db._fetchall("PRAGMA table_info(suppressions)")}
    assert "project_id" in cols
    assert "fingerprint" in cols
    # Новый PK — (project_id, fingerprint): одна строка на проект.
    await SuppressionStore(db, "p1").create(Suppression(fingerprint="fp-1", reason="r"))
    await SuppressionStore(db, "p2").create(Suppression(fingerprint="fp-1", reason="r"))
    rows = db._fetchall("SELECT project_id, fingerprint FROM suppressions")
    assert {(r["project_id"], r["fingerprint"]) for r in rows} == {("p1", "fp-1"), ("p2", "fp-1")}
    db.close()


async def test_suppression_expired_is_not_active(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = SuppressionStore(db, "p1")
    store.init_schema()

    await store.create(
        Suppression(fingerprint="fp-1", reason="r", expires_at="2020-01-01T00:00:00+00:00")
    )
    assert await store.is_suppressed("fp-1") is False
    assert await store.filter_active([_finding("fp-1")]) == [_finding("fp-1")]
    db.close()
