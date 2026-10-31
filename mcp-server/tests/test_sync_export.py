"""Тесты реконструкции событий из локальных БД (MS-3, sync/export.py).

Критерий корректности: событийная последовательность, которую fold на master
(ADR-0006 §3.4, матрица §2.1) сворачивает в тот же статус, что хранится
локально в shown_findings.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sync_helpers import insert_shown, insert_suppression, make_db

from appsecgate_mcp.sync.export import ExportError, export_events

_KNOWN_EVENT_TYPES = {
    "discovered",
    "reaffirmed",
    "not_found_in_scope",
    "verify_fixed",
    "verify_not_fixed",
    "verify_wont_fix",
    "suppressed",
    "suppression_expired",
    "unsuppressed",
    "reopened",
    "config_policy",
}


def _event_types(events, fp: str) -> list[str]:
    return [e["event_type"] for e in events if e["fp"] == fp]


def test_export_missing_db_raises(tmp_path):
    with pytest.raises(ExportError, match="not found"):
        export_events(tmp_path / "nope.db")


def test_export_empty_db_ok(tmp_path):
    db = make_db(tmp_path)
    result = export_events(db)
    assert result.events == []
    assert result.project_count == 0
    assert result.finding_count == 0


def test_export_shown_emits_discovered(tmp_path):
    db = make_db(tmp_path)
    insert_shown(
        db,
        "fp-1",
        first_seen_branch="feature/x",
        first_seen_commit="abc123",
        last_seen_branch="feature/x",
        last_seen_commit="abc123",
    )
    result = export_events(db)
    assert _event_types(result.events, "fp-1") == ["discovered"]
    event = result.events[0]
    assert event["project_key"] == "pid-1"
    assert event["rule_id"] == "rule.one"
    assert event["file"] == "src/a.py"
    assert event["severity"] == "high"
    assert event["at"] == "2026-10-01T10:00:00.000000+00:00"
    assert event["branch"] == "feature/x"
    assert event["first_seen_branch"] == "feature/x"


def test_export_reaffirmed_when_reseen(tmp_path):
    db = make_db(tmp_path)
    insert_shown(
        db,
        "fp-1",
        first_seen_at="2026-10-01T10:00:00.000000+00:00",
        last_seen_at="2026-10-02T10:00:00.000000+00:00",
        last_seen_branch="feature/x",
        last_seen_commit="def456",
    )
    result = export_events(db)
    assert _event_types(result.events, "fp-1") == ["discovered", "reaffirmed"]
    assert result.events[1]["at"] == "2026-10-02T10:00:00.000000+00:00"
    assert result.events[1]["last_seen_branch"] == "feature/x"


def test_export_no_reaffirmed_when_single_observation(tmp_path):
    db = make_db(tmp_path)
    insert_shown(db, "fp-1")  # first_seen_at == last_seen_at
    assert _event_types(export_events(db).events, "fp-1") == ["discovered"]


def test_export_potentially_fixed(tmp_path):
    db = make_db(tmp_path)
    insert_shown(
        db,
        "fp-1",
        status="POTENTIALLY_FIXED",
        missed_scan_count=3,
        status_updated_at="2026-10-05T10:00:00.000000+00:00",
    )
    result = export_events(db)
    assert _event_types(result.events, "fp-1") == ["discovered", "not_found_in_scope"]
    event = result.events[1]
    assert event["at"] == "2026-10-05T10:00:00.000000+00:00"
    assert event["missed_scan_count"] == 3


def test_export_fixed_orders_not_found_before_verify(tmp_path):
    db = make_db(tmp_path)
    insert_shown(
        db,
        "fp-1",
        status="FIXED",
        fixed_at="2026-10-06T10:00:00.000000+00:00",
        fixed_confirmed_by="verify_fix",
        status_updated_at="2026-10-06T10:00:00.000000+00:00",
    )
    result = export_events(db)
    types = _event_types(result.events, "fp-1")
    assert types == ["discovered", "not_found_in_scope", "verify_fixed"]
    not_found, verify = result.events[1], result.events[2]
    # Матрица §2.1: SHOWN --not_found--> POTENTIALLY_FIXED --verify_fixed--> FIXED.
    assert not_found["at"] < verify["at"]
    assert verify["at"] == "2026-10-06T10:00:00.000000+00:00"
    assert verify["verified_status"] == "fixed"
    assert verify["note"] == "verify_fix"


def test_export_reopened_with_fixed_at(tmp_path):
    db = make_db(tmp_path)
    insert_shown(
        db,
        "fp-1",
        status="REOPENED",
        fixed_at="2026-10-06T10:00:00.000000+00:00",
        status_updated_at="2026-10-07T10:00:00.000000+00:00",
        last_seen_branch="feature/x",
        last_seen_commit="new",
    )
    result = export_events(db)
    types = _event_types(result.events, "fp-1")
    # FIXED --reopened--> REOPENED (правило 2 §3.4); reopened позже verify_fixed.
    assert types == ["discovered", "not_found_in_scope", "verify_fixed", "reopened"]
    ats = [e["at"] for e in result.events]
    assert ats == sorted(ats)


def test_export_reopened_without_fixed_at_approximates_shown(tmp_path):
    """SHOWN→REOPENED не имеет пути в матрице §2.1 — аппроксимируем verify_not_fixed."""
    db = make_db(tmp_path)
    insert_shown(
        db,
        "fp-1",
        status="REOPENED",
        status_updated_at="2026-10-07T10:00:00.000000+00:00",
    )
    assert _event_types(export_events(db).events, "fp-1") == [
        "discovered",
        "verify_not_fixed",
    ]


def test_export_suppressed_takes_scope_from_suppressions(tmp_path):
    db = make_db(tmp_path)
    insert_shown(
        db,
        "fp-1",
        status="SUPPRESSED",
        suppressed_at="2026-10-08T10:00:00.000000+00:00",
        suppress_reason="false positive",
    )
    insert_suppression(
        db,
        "fp-1",
        scope="ci",
        reason="false positive",
        expires_at="2026-11-01T00:00:00.000000+00:00",
        created_at="2026-10-08T10:00:00.000000+00:00",
    )
    result = export_events(db)
    assert _event_types(result.events, "fp-1") == ["discovered", "suppressed"]
    event = result.events[1]
    assert event["scope"] == "ci"
    assert event["reason"] == "false positive"
    assert event["expires_at"] == "2026-11-01T00:00:00.000000+00:00"


def test_export_suppressed_defaults_to_local_scope(tmp_path):
    """SUPPRESSED без записи suppressions → scope=local (консервативно, не влияет на CI)."""
    db = make_db(tmp_path)
    insert_shown(db, "fp-1", status="SUPPRESSED", suppressed_at="2026-10-08T10:00:00.000000+00:00")
    event = export_events(db).events[1]
    assert event["scope"] == "local"


def test_export_wont_fix(tmp_path):
    db = make_db(tmp_path)
    insert_shown(
        db,
        "fp-1",
        status="WONT_FIX",
        wont_fix_at="2026-10-09T10:00:00.000000+00:00",
        wont_fix_reason="by design",
    )
    result = export_events(db)
    assert _event_types(result.events, "fp-1") == ["discovered", "verify_wont_fix"]
    event = result.events[1]
    assert event["verified_status"] == "wont_fix"
    assert event["note"] == "by design"


def test_export_wont_fix_without_reason_gets_default_note(tmp_path):
    """Контракт MasterEvent требует непустой note для verify_wont_fix."""
    db = make_db(tmp_path)
    insert_shown(db, "fp-1", status="WONT_FIX", wont_fix_at="2026-10-09T10:00:00.000000+00:00")
    assert export_events(db).events[1]["note"] == "wont_fix"


def test_export_suppression_without_shown_row(tmp_path):
    """Suppression до первого показа: событие suppressed без finding-контекста."""
    db = make_db(tmp_path)
    insert_suppression(db, "fp-9", scope="global", reason="policy")
    result = export_events(db)
    assert [e["event_type"] for e in result.events] == ["suppressed"]
    event = result.events[0]
    assert event["fp"] == "fp-9"
    assert event["scope"] == "global"
    assert event["at"] == "2026-10-01T10:00:00.000000+00:00"


def test_export_projects_are_isolated(tmp_path):
    db = make_db(tmp_path)
    insert_shown(db, "fp-1", project_id="pid-1")
    insert_shown(db, "fp-2", project_id="pid-2")
    all_result = export_events(db)
    assert all_result.project_count == 2
    assert {e["project_key"] for e in all_result.events} == {"pid-1", "pid-2"}
    filtered = export_events(db, project_id="pid-1")
    assert filtered.project_count == 1
    assert {e["project_key"] for e in filtered.events} == {"pid-1"}


def test_export_client_event_ids_stable_across_runs(tmp_path):
    db = make_db(tmp_path)
    insert_shown(db, "fp-1", status="FIXED", fixed_at="2026-10-06T10:00:00.000000+00:00")
    first = [(e["client_event_id"], e["event_type"]) for e in export_events(db).events]
    second = [(e["client_event_id"], e["event_type"]) for e in export_events(db).events]
    assert first == second
    assert len(first) == len(set(eid for eid, _ in first))


def test_export_events_schema_is_master_contract(tmp_path):
    """Поля событий соответствуют контракту MasterEvent (ADR-0004 §5.1, ADR-0006 §3.3)."""
    db = make_db(tmp_path)
    insert_shown(
        db,
        "fp-1",
        status="POTENTIALLY_FIXED",
        missed_scan_count=1,
        status_updated_at="2026-10-05T10:00:00.000000+00:00",
    )
    for event in export_events(db).events:
        assert event["schema_version"] == 1
        assert event["event_type"] in _KNOWN_EVENT_TYPES
        assert event["project_key"] == "pid-1"
        assert uuid.UUID(event["client_event_id"])
        assert "fp" in event
        # at — валидный UTC ISO-8601 (Z или +00:00).
        parsed = datetime.fromisoformat(
            event["at"][:-1] + "+00:00" if event["at"].endswith("Z") else event["at"]
        )
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() is not None


def test_export_summary_counts(tmp_path):
    db = make_db(tmp_path)
    insert_shown(db, "fp-1", status="FIXED", fixed_at="2026-10-06T10:00:00.000000+00:00")
    insert_shown(db, "fp-2")
    result = export_events(db)
    assert result.finding_count == 2
    assert result.by_event["discovered"] == 2
    assert result.by_event["verify_fixed"] == 1
    assert result.by_event["not_found_in_scope"] == 1
