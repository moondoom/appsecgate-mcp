"""AuditLogStore: append-only журнал, фильтры, запрет UPDATE/DELETE."""

from __future__ import annotations

import sqlite3

import pytest
from helpers import make_event

from appsecgate_master.storage import AuditLogStore, MasterEventStore


async def test_audit_recorded_for_accepted(events_store: MasterEventStore):
    event = make_event("discovered")
    await events_store.ingest([event])
    rows = await events_store.audit.list()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "accepted"
    assert rows[0]["client_event_id"] == event.client_event_id
    assert rows[0]["event_type"] == "discovered"
    assert rows[0]["fp"] == event.fp
    assert rows[0]["project_key"] == "proj"


async def test_audit_recorded_for_rejected(events_store: MasterEventStore):
    event = make_event("suppressed", scope="local", reason="api_key=abc1234567890xyz")
    await events_store.ingest([event])
    rows = await events_store.audit.list()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "rejected:redaction"


async def test_audit_list_filters(events_store: MasterEventStore):
    a = make_event("discovered", project_key="p1")
    b = make_event("reaffirmed", project_key="p2")
    await events_store.ingest([a, b])
    rows = await events_store.audit.list(project_key="p1")
    assert len(rows) == 1
    assert rows[0]["project_key"] == "p1"
    assert len(await events_store.audit.list(limit=1)) == 1


async def test_audit_record_direct(events_store: MasterEventStore):
    event = make_event("discovered")
    await events_store.audit.record(event, "accepted", "2026-10-31T12:00:00Z")
    assert await events_store.audit.count() == 1


async def test_audit_append_only_enforced(master_db, events_store: MasterEventStore):
    event = make_event("discovered")
    await events_store.ingest([event])
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        await master_db.execute("UPDATE audit_log SET outcome = 'accepted'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        await master_db.execute("DELETE FROM audit_log")


def test_audit_store_has_no_mutation_api():
    """API append-only: методов UPDATE/DELETE не существует."""
    methods = {name for name in dir(AuditLogStore) if not name.startswith("_")}
    assert not ({"update", "delete", "remove", "update_one", "delete_many"} & methods)
