"""Тесты PR 1.1: проектная идентичность и слой данных.

Покрывает:
  * детерминизм ``_compute_project_id`` (ша256 от realpath);
  * ``project_alias`` = basename пути;
  * фиксация ``project_id`` в сессии (ошибка при смене пути);
  * upsert в ``projects`` со стабильным ``first_seen_at``;
  * ось ``project_id`` в ``shown_findings`` и recreate старой схемы.
"""

from __future__ import annotations

import os

import pytest

from appsecgate_mcp import server
from appsecgate_mcp.config.loader import ConfigLoader
from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores import ProjectsStore, ShownFindingsStore


def _make_finding(fp: str) -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="test.rule",
        severity=Severity.HIGH,
        file_path="app.py",
        scanner="semgrep",
        category=Category.SAST,
    )


@pytest.fixture
def fresh_session(tmp_path, monkeypatch):
    """Изолированная сессия (без сети/домашнего каталога), как в test_session_lock."""
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("APPSECGATE_MCP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(tmp_path / "trivy"))
    state = server.SessionState()
    state.config_loader = ConfigLoader(tmp_path / "no-default.yaml")
    return state


def test_compute_project_id_deterministic(tmp_path):
    p = str(tmp_path / "app")
    assert server._compute_project_id(p) == server._compute_project_id(p)
    assert len(server._compute_project_id(p)) == 16


def test_compute_project_id_canonicalizes_path(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    assert server._compute_project_id(str(real)) == server._compute_project_id(str(link))
    assert server._compute_project_id(str(real / ".")) == server._compute_project_id(str(real))


@pytest.mark.asyncio
async def test_project_id_and_alias_set_on_initialize(fresh_session, tmp_path):
    root = tmp_path / "my-project"
    root.mkdir()
    await fresh_session.initialize(str(root))

    assert fresh_session.project_id == server._compute_project_id(str(root))
    assert fresh_session.project_alias == "my-project"
    await fresh_session.close()


@pytest.mark.asyncio
async def test_change_project_path_raises(fresh_session, tmp_path):
    root_a = tmp_path / "a"
    root_a.mkdir()
    root_b = tmp_path / "b"
    root_b.mkdir()

    await fresh_session.initialize(str(root_a))
    with pytest.raises(ValueError, match="project_path изменился"):
        await fresh_session.initialize(str(root_b), force=True)
    # Повторный init того же пути — не ошибка.
    await fresh_session.initialize(str(root_a), force=True)
    await fresh_session.close()


@pytest.mark.asyncio
async def test_projects_upsert_keeps_first_seen_at(tmp_path, monkeypatch):
    from appsecgate_mcp.storage import stores as stores_mod

    clock = {"t": 0}

    def fake_now() -> str:
        clock["t"] += 1
        return f"2026-01-01T00:00:{clock['t']:02d}+00:00"

    monkeypatch.setattr(stores_mod, "_now_iso", fake_now)

    db = Database(tmp_path / "shown.db")
    db.connect()
    store = ProjectsStore(db)
    store.init_schema()

    await store.upsert("p1", "alias-a", "/path/a")
    first_seen = (await store.get("p1"))["first_seen_at"]

    await store.upsert("p1", "alias-b", "/path/a")
    row = await store.get("p1")
    assert row["first_seen_at"] == first_seen
    assert row["last_seen_at"] != first_seen
    assert row["project_alias"] == "alias-b"
    assert row["project_path"] == "/path/a"

    db.close()


@pytest.mark.asyncio
async def test_shown_findings_writes_project_id(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = ShownFindingsStore(db, "proj-1")
    store.init_schema()

    await store.record_shown(_make_finding("fp-1"))
    rows = await store.get_all(limit=10)
    assert rows[0]["project_id"] == "proj-1"
    assert rows[0]["project_id"] is not None

    db.close()


@pytest.mark.asyncio
async def test_shown_two_projects_no_collision(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    s1 = ShownFindingsStore(db, "p1")
    s1.init_schema()
    s2 = ShownFindingsStore(db, "p2")

    await s1.record_shown(_make_finding("fp-a"))
    await s2.record_shown(_make_finding("fp-b"))

    rows = await s1.get_all(limit=100)
    by_pid = {(r["fingerprint"], r["project_id"]) for r in rows}
    assert ("fp-a", "p1") in by_pid
    assert ("fp-b", "p2") in by_pid

    db.close()


@pytest.mark.asyncio
async def test_shown_findings_recreates_old_schema(tmp_path):
    """Старая таблица без project_id пересоздаётся (No-migration)."""
    db = Database(tmp_path / "shown.db")
    db.connect()
    # Эмулируем схему до PR 1.1.
    db._execute_ddl(
        """
        CREATE TABLE shown_findings (
            fingerprint TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            severity TEXT NOT NULL,
            scanner TEXT NOT NULL,
            first_shown_at TIMESTAMP NOT NULL,
            last_shown_at TIMESTAMP NOT NULL,
            show_count INTEGER DEFAULT 1,
            status TEXT NOT NULL
        );
        """
    )

    store = ShownFindingsStore(db, "proj-1")
    store.init_schema()

    cols = [r["name"] for r in db._fetchall("PRAGMA table_info(shown_findings)")]
    assert "project_id" in cols
    assert "logical_id" in cols
    assert "status_updated_at" in cols

    db.close()
