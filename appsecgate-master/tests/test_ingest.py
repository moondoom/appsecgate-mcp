"""Приём событий: идемпотентность, schema_version, redaction, append-only."""

from __future__ import annotations

import sqlite3

import pytest
from helpers import make_event, uid

from appsecgate_master.contracts.events import SCHEMA_VERSION
from appsecgate_master.storage import MasterEventStore
from appsecgate_master.storage.db import Database


async def test_ingest_accepts_valid_event(events_store: MasterEventStore):
    event = make_event("discovered", fp="rule|file|1")
    outcomes = await events_store.ingest([event])
    assert outcomes[0].client_event_id == event.client_event_id
    assert outcomes[0].outcome == "accepted"
    assert await events_store.count() == 1
    assert await events_store.audit.count() == 1


async def test_ingest_idempotent_by_client_event_id(events_store: MasterEventStore):
    event = make_event("discovered")
    first = await events_store.ingest([event])
    second = await events_store.ingest([event])  # тот же client_event_id
    assert first[0].outcome == "accepted"
    assert second[0].outcome == "duplicate"
    assert await events_store.count() == 1  # строка одна
    audit = await events_store.audit.list()
    assert [row["outcome"] for row in audit] == ["duplicate", "accepted"]  # обе записи


async def test_ingest_rejects_wrong_schema_version(events_store: MasterEventStore):
    event = make_event("discovered", schema_version=SCHEMA_VERSION + 1)
    outcome = (await events_store.ingest([event]))[0]
    assert outcome.outcome == "rejected:schema_version"
    assert await events_store.count() == 0
    audit = await events_store.audit.list()
    assert audit[0]["outcome"] == "rejected:schema_version"


async def test_ingest_rejects_secret_in_note(events_store: MasterEventStore):
    """§5.4: секрет в note → rejected:redaction, в events не попадает."""
    event = make_event("verify_wont_fix", note="AKIAIOSFODNN7EXAMPLE — ключ в сообщении")
    outcome = (await events_store.ingest([event]))[0]
    assert outcome.outcome == "rejected:redaction"
    assert await events_store.count() == 0
    assert (await events_store.audit.list())[0]["outcome"] == "rejected:redaction"


async def test_ingest_rejects_secret_in_reason(events_store: MasterEventStore):
    event = make_event("suppressed", scope="local", reason="token=superSecret1234567890")
    outcome = (await events_store.ingest([event]))[0]
    assert outcome.outcome == "rejected:redaction"
    assert await events_store.count() == 0


async def test_ingest_batch_mixed_outcomes(events_store: MasterEventStore):
    good = make_event("discovered")
    bad_secret = make_event("suppressed", scope="local", reason="api_key=abc1234567890xyz")
    bad_version = make_event("reaffirmed", schema_version=999)
    outcomes = await events_store.ingest([good, bad_secret, bad_version])
    assert [o.outcome for o in outcomes] == [
        "accepted",
        "rejected:redaction",
        "rejected:schema_version",
    ]
    assert await events_store.count() == 1
    assert await events_store.audit.count() == 3


async def test_events_table_append_only_trigger(master_db: Database):
    event = make_event("discovered")
    await MasterEventStore(master_db).ingest([event])
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        await master_db.execute("UPDATE events SET at = '2026-11-01T00:00:00Z'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        await master_db.execute("DELETE FROM events")


async def test_list_events_roundtrip(events_store: MasterEventStore):
    event = make_event("verify_fixed", fp="fp|f|1", at="2026-10-31T12:00:00Z", event_id=uid())
    await events_store.ingest([event])
    listed = await events_store.list_events(project_key=event.project_key)
    assert len(listed) == 1
    restored = listed[0]
    assert restored.client_event_id == event.client_event_id
    assert restored.event_id == event.event_id  # event_id из таблицы восстановлен
    assert restored.event_type == event.event_type
    assert restored.fp == event.fp


async def test_list_events_filters(events_store: MasterEventStore):
    a = make_event("discovered", project_key="p1", at="2026-10-31T12:00:00Z")
    b = make_event("reaffirmed", project_key="p2", at="2026-10-31T13:00:00Z")
    await events_store.ingest([a, b])
    assert len(await events_store.list_events(project_key="p1")) == 1
    assert len(await events_store.list_events(since="2026-10-31T12:30:00Z")) == 1
    assert len(await events_store.list_events(limit=1)) == 1
