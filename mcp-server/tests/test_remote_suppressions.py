"""MS-5: отдельный remote-suppression слой и его применение при скане."""

from __future__ import annotations

import pytest
from sync_helpers import insert_shown, make_db

from appsecgate_mcp.models.finding import Category, Finding, Severity, Suppression
from appsecgate_mcp.orchestration.suppression import apply_suppression_filters
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores import RemoteSuppressionStore, SuppressionStore
from appsecgate_mcp.sync.export import export_events


def _finding(fp: str) -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="test.rule",
        severity=Severity.HIGH,
        file_path="a.py",
        scanner="semgrep",
        category=Category.SAST,
    )


def _suppression(fp: str, **kwargs) -> Suppression:
    values = {"reason": "central", "scope": "ci", **kwargs}
    return Suppression(fingerprint=fp, **values)


async def test_remote_replace_filters_and_does_not_touch_local(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    local = SuppressionStore(db, "p1")
    local.init_schema()
    remote = RemoteSuppressionStore(db, "p1")
    remote.init_schema()
    await local.create(Suppression(fingerprint="local-fp", reason="mine"))
    await remote.replace_all([_suppression("remote-fp")])

    assert await local.is_suppressed("local-fp")
    assert await remote.is_suppressed("remote-fp")
    assert not await remote.is_suppressed("local-fp")
    assert (await local.get("local-fp")).reason == "mine"
    db.close()


async def test_remote_replace_empty_and_project_isolation(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    first = RemoteSuppressionStore(db, "p1")
    second = RemoteSuppressionStore(db, "p2")
    first.init_schema()
    await first.replace_all([_suppression("fp-1")])
    await second.replace_all([_suppression("fp-2", scope="global")])

    await first.replace_all([])
    assert await first.list_all() == []
    assert [item.fingerprint for item in await second.list_all()] == ["fp-2"]
    db.close()


async def test_remote_expired_does_not_filter(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = RemoteSuppressionStore(db, "p1")
    store.init_schema()
    await store.replace_all([_suppression("fp-1", expires_at="2020-01-01T00:00:00+00:00")])
    assert not await store.is_suppressed("fp-1")
    assert await store.filter_active([_finding("fp-1")]) == [_finding("fp-1")]
    db.close()


async def test_remote_replace_is_transactional(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = RemoteSuppressionStore(db, "p1")
    store.init_schema()
    await store.replace_all([_suppression("old")])
    with pytest.raises(Exception, match="UNIQUE"):
        await store.replace_all([_suppression("new"), _suppression("new")])
    assert [item.fingerprint for item in await store.list_all()] == ["old"]
    db.close()


async def test_combined_local_and_remote_filters(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    local = SuppressionStore(db, "p1")
    local.init_schema()
    remote = RemoteSuppressionStore(db, "p1")
    remote.init_schema()
    await local.create(Suppression(fingerprint="local", reason="mine"))
    await remote.replace_all([_suppression("remote")])
    findings = [_finding("local"), _finding("remote"), _finding("visible")]
    filtered = await apply_suppression_filters(findings, local_store=local, remote_store=remote)
    assert filtered == [_finding("visible")]
    db.close()


async def test_remote_suppressions_are_not_exported_back(tmp_path):
    path = make_db(tmp_path)
    insert_shown(path, "remote-fp")
    db = Database(path)
    db.connect()
    store = RemoteSuppressionStore(db, "pid-1")
    store.init_schema()
    await store.replace_all([_suppression("remote-fp")])
    db.close()

    exported = export_events(path, project_id="pid-1")
    assert [event["event_type"] for event in exported.events] == ["discovered"]
