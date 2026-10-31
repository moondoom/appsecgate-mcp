"""Schema version management (ADR-0005 §2.7): schema_meta + drop-on-mismatch.

Механизм работает в ``init_databases()`` (``storage/db.py``): свежая БД
получает ``schema_version`` без дропа; БД с другой версией или без
``schema_meta`` дропается полностью (views + таблицы, включая
``sqlite_sequence``) и пересоздаётся store-классами.
"""

from __future__ import annotations

import logging

from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.storage.db import Database, init_databases
from appsecgate_mcp.storage.migrations import SCHEMA_VERSION, ensure_schema_version
from appsecgate_mcp.storage.query import init_views
from appsecgate_mcp.storage.stores import (
    FeedbackStore,
    FindingContextStore,
    FindingIdentityStore,
    FixAttemptsStore,
    ProjectsStore,
    ScanCacheStore,
    ShownFindingsStore,
    SqlAuditLogStore,
    SuppressionStore,
)


def _paths(tmp_path) -> dict[str, object]:
    return {
        "shown": tmp_path / "shown_findings.db",
        "feedback": tmp_path / "feedback.db",
        "scan_cache": tmp_path / "scan_cache.db",
    }


def _init_shown_schema(db: Database, project_id: str = "pid-1") -> None:
    """Полная схема shown_findings.db: все store-таблицы + публичные views."""
    ShownFindingsStore(db, project_id).init_schema()
    SuppressionStore(db, project_id).init_schema()
    ProjectsStore(db).init_schema()
    FindingIdentityStore(db).init_schema()
    FindingContextStore(db).init_schema()
    FixAttemptsStore(db).init_schema()
    SqlAuditLogStore(db).init_schema()
    init_views(db)


def _make_finding(fp: str) -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="test.rule",
        severity=Severity.HIGH,
        file_path="app.py",
        scanner="semgrep",
        category=Category.SAST,
    )


def _version(db: Database) -> str | None:
    row = db._fetchone("SELECT value FROM schema_meta WHERE key = 'schema_version'")
    return str(row["value"]) if row else None


def _objects(db: Database, obj_type: str) -> list[str]:
    rows = db._fetchall("SELECT name FROM sqlite_master WHERE type = ?", (obj_type,))
    return [str(r["name"]) for r in rows]


async def test_fresh_databases_get_version_without_drop(tmp_path, caplog):
    """Свежая БД: schema_meta создаётся, версия проставляется, дропа нет."""
    with caplog.at_level(logging.WARNING):
        dbs = await init_databases(_paths(tmp_path))
    for _name, db in dbs.items():
        assert "schema_meta" in _objects(db, "table")
        assert _version(db) == SCHEMA_VERSION

    # Схема создаётся store-классами после init_databases (session._init_storage).
    _init_shown_schema(dbs["shown"])
    FeedbackStore(dbs["feedback"]).init_schema()
    ScanCacheStore(dbs["scan_cache"]).init_schema()
    assert not [r for r in caplog.records if "schema_version" in r.message]


async def test_matching_version_preserves_data(tmp_path):
    """Версия совпадает — данные переживают повторную инициализацию."""
    paths = _paths(tmp_path)
    dbs = await init_databases(paths)
    _init_shown_schema(dbs["shown"])
    await ShownFindingsStore(dbs["shown"], "pid-1").record_shown(
        _make_finding("fp-1"), logical_id="lid-1"
    )

    dbs2 = await init_databases(paths)
    rows = await ShownFindingsStore(dbs2["shown"], "pid-1").get_all()
    assert [r["fingerprint"] for r in rows] == ["fp-1"]


async def test_drop_on_schema_mismatch_removes_views_and_sequence(tmp_path):
    """Несовпадение версии: drop views + таблиц + sqlite_sequence, потом пересоздание."""
    paths = _paths(tmp_path)
    dbs = await init_databases(paths)
    _init_shown_schema(dbs["shown"])
    FeedbackStore(dbs["feedback"]).init_schema()

    # Данные и AUTOINCREMENT-счётчики (sqlite_sequence появляется после INSERT).
    await ShownFindingsStore(dbs["shown"], "pid-1").record_shown(
        _make_finding("fp-1"), logical_id="lid-1"
    )
    old_id = await FeedbackStore(dbs["feedback"]).save(
        "fp-1", "CONFIRMED", reason="seen"
    )
    assert old_id >= 1
    assert _objects(dbs["shown"], "view")
    assert "sqlite_sequence" in _objects(dbs["shown"], "table")

    # Портим версию и перепроверяем.
    dbs["shown"]._write(
        "UPDATE schema_meta SET value='999' WHERE key='schema_version'"
    )
    dbs["feedback"]._write(
        "UPDATE schema_meta SET value='999' WHERE key='schema_version'"
    )
    for db in dbs.values():
        db.close()

    dbs2 = await init_databases(paths)
    assert _version(dbs2["shown"]) == SCHEMA_VERSION
    assert _version(dbs2["feedback"]) == SCHEMA_VERSION
    assert _objects(dbs2["shown"], "view") == []
    # sqlite_sequence нельзя DROP (SQLite), но после дропа он очищен:
    # счётчики AUTOINCREMENT сброшены, что проверяется ниже по id=1.
    seq_row = dbs2["shown"]._fetchone("SELECT COUNT(*) AS n FROM sqlite_sequence")
    assert seq_row is not None and seq_row["n"] == 0

    # Пересоздание схемы store-классами (session flow после init_databases).
    _init_shown_schema(dbs2["shown"])
    FeedbackStore(dbs2["feedback"]).init_schema()
    ScanCacheStore(dbs2["scan_cache"]).init_schema()
    assert _objects(dbs2["shown"], "view")
    assert await ShownFindingsStore(dbs2["shown"], "pid-1").get_all() == []

    # AUTOINCREMENT-счётчик сброшен: первый INSERT после дропа получает id=1.
    new_id = await FeedbackStore(dbs2["feedback"]).save(
        "fp-2", "CONFIRMED", reason="after drop"
    )
    assert new_id == 1


async def test_legacy_db_without_schema_meta_is_dropped(tmp_path):
    """Старая БД (таблицы без schema_meta) дропается, данные не сохраняются."""
    path = _paths(tmp_path)["shown"]

    legacy = Database(path)
    legacy.connect()
    ShownFindingsStore(legacy, "pid-1").init_schema()
    # В до-schema_meta мире finding_identity уже существовала — record_shown
    # с logical_id пишет связку именно туда (ADR-0005 §2.8, К1).
    FindingIdentityStore(legacy).init_schema()
    await ShownFindingsStore(legacy, "pid-1").record_shown(
        _make_finding("fp-legacy"), logical_id="lid-1"
    )
    legacy.close()

    migrated = Database(path)
    migrated.connect()
    assert ensure_schema_version(migrated) is True
    _init_shown_schema(migrated)
    assert await ShownFindingsStore(migrated, "pid-1").get_all() == []
    migrated.close()


async def test_all_three_databases_get_schema_meta(tmp_path):
    """Механизм покрывает все три БД: shown, feedback, scan_cache."""
    dbs = await init_databases(_paths(tmp_path))
    for _name, db in dbs.items():
        assert "schema_meta" in _objects(db, "table")
        assert _version(db) == SCHEMA_VERSION


async def test_mismatch_logs_warning(tmp_path, caplog):
    """Drop по несовпадению версии логируется как warning."""
    dbs = await init_databases(_paths(tmp_path))
    dbs["shown"]._write(
        "UPDATE schema_meta SET value='0' WHERE key='schema_version'"
    )

    with caplog.at_level(logging.WARNING, logger="appsecgate_mcp.storage.migrations"):
        assert ensure_schema_version(dbs["shown"]) is True

    assert any("schema_version" in r.message for r in caplog.records)
    assert _version(dbs["shown"]) == SCHEMA_VERSION

