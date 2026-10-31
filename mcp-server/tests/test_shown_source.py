"""Тесты shown-snapshot: парсер, retention, SnapshotShownSource (ADR-0003 §6)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from appsecgate_mcp.orchestration.shown_source import (
    ShownRecord,
    ShownSnapshot,
    ShownSnapshotError,
    SnapshotShownSource,
    parse_shown_snapshot,
)

pytestmark = pytest.mark.asyncio


def _line(fp: str, **extra) -> str:
    record = {"fp": fp, "rule_id": "r", "file": "a.py", "line": 1, "severity": "low", **extra}
    return json.dumps(record)


async def test_parse_snapshot_basic(tmp_path):
    path = tmp_path / "shown.ndjson"
    # Свежая дата: статичная дата против RETENTION_DAYS=30 — «бомба времени».
    fresh = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    path.write_text(
        _line("fp-1", verified_status="fixed")
        + "\n"
        + _line("fp-2", suppression_scope="ci", shown_at=fresh)
        + "\n\n",
        encoding="utf-8",
    )
    snapshot = parse_shown_snapshot(path)
    assert len(snapshot.records) == 2
    assert snapshot.records[0].verified_status == "fixed"
    assert snapshot.records[1].suppression_scope == "ci"
    assert snapshot.records[1].shown_at == fresh
    assert snapshot.expired_count == 0


async def test_parse_rejects_invalid_json(tmp_path):
    path = tmp_path / "shown.ndjson"
    path.write_text("this is not json\n", encoding="utf-8")
    with pytest.raises(ShownSnapshotError, match="invalid JSON"):
        parse_shown_snapshot(path)


async def test_parse_rejects_record_without_fp(tmp_path):
    path = tmp_path / "shown.ndjson"
    path.write_text(json.dumps({"rule_id": "r"}) + "\n", encoding="utf-8")
    with pytest.raises(ShownSnapshotError, match="'fp'"):
        parse_shown_snapshot(path)


async def test_parse_ignores_expired_records(tmp_path):
    path = tmp_path / "shown.ndjson"
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    path.write_text(_line("fp-old", shown_at=old) + "\n", encoding="utf-8")
    snapshot = parse_shown_snapshot(path)
    assert snapshot.records == []
    assert snapshot.expired_count == 1


async def test_parse_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        parse_shown_snapshot(tmp_path / "nope.ndjson")


async def test_snapshot_source_returns_record_and_none():
    snapshot = ShownSnapshot(records=[ShownRecord(fingerprint="fp", suppression_scope="global")])
    source = SnapshotShownSource(snapshot)
    record = await source.record("fp")
    assert record is not None
    assert record.suppression_scope == "global"
    assert await source.record("unknown") is None
