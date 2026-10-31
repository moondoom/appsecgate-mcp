"""Тесты durable outbox (MS-3, sync/outbox.py)."""

from __future__ import annotations

import json

from appsecgate_mcp.sync.outbox import Outbox


def _event(eid: str, extra: dict | None = None) -> dict:
    return {"client_event_id": eid, "event_type": "discovered", **(extra or {})}


def test_outbox_append_read_roundtrip(tmp_path):
    outbox = Outbox(tmp_path / "outbox.ndjson")
    assert outbox.append([_event("a"), _event("b")]) == 2
    events = outbox.read()
    assert [e["client_event_id"] for e in events] == ["a", "b"]
    assert outbox.append([_event("c")]) == 1


def test_outbox_append_dedup_by_client_event_id(tmp_path):
    outbox = Outbox(tmp_path / "outbox.ndjson")
    outbox.append([_event("a"), _event("b")])
    assert outbox.append([_event("b"), _event("c")]) == 1
    assert [e["client_event_id"] for e in outbox.read()] == ["a", "b", "c"]


def test_outbox_remove_sent(tmp_path):
    outbox = Outbox(tmp_path / "outbox.ndjson")
    outbox.append([_event("a"), _event("b"), _event("c")])
    assert outbox.remove({"a", "c"}) == 2
    assert [e["client_event_id"] for e in outbox.read()] == ["b"]


def test_outbox_quarantine_rejected(tmp_path):
    outbox = Outbox(tmp_path / "outbox.ndjson")
    outbox.append([_event("a"), _event("b")])
    assert outbox.quarantine({"a"}) == 1
    assert [e["client_event_id"] for e in outbox.read()] == ["b"]
    rejected = (tmp_path / "outbox.ndjson.rejected").read_text(encoding="utf-8")
    assert json.loads(rejected)["client_event_id"] == "a"


def test_outbox_corrupt_line_quarantined(tmp_path):
    outbox = Outbox(tmp_path / "outbox.ndjson")
    outbox.append([_event("a")])
    (tmp_path / "outbox.ndjson").write_text("not-json\n", encoding="utf-8")
    assert outbox.read() == []
    corrupt = (tmp_path / "outbox.ndjson.corrupt").read_text(encoding="utf-8")
    assert corrupt == "not-json\n"


def test_outbox_missing_file_reads_empty(tmp_path):
    outbox = Outbox(tmp_path / "nope.ndjson")
    assert outbox.read() == []
    assert outbox.remove({"a"}) == 0
    assert outbox.quarantine({"a"}) == 0


def test_outbox_append_creates_parent_dirs(tmp_path):
    outbox = Outbox(tmp_path / "deep" / "dir" / "outbox.ndjson")
    assert outbox.append([_event("a")]) == 1
    assert (tmp_path / "deep" / "dir" / "outbox.ndjson").is_file()
