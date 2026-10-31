"""Параность snapshot-replay (§3.3) и master-агрегата (ADR-0006 §6, SM-4/MS-2).

Оба пути используют один fold (appsecgate_master.aggregate.fold) — статусы
совпадают на любом потоке событий. Тест проверяет:
1. ``rebuild()`` через БД даёт то же состояние, что и чистый ``fold_events``.
2. Снапшот-события §3.3 (поля event/project_id) парсятся в MasterEvent
   (алиасы) и replay даёт ожидаемый статус.
"""

from __future__ import annotations

from dataclasses import asdict

from helpers import BASE_AT, FP, make_event, prime, shift_at

from appsecgate_master.aggregate.fold import fold_events
from appsecgate_master.aggregate.state import FindingState
from appsecgate_master.contracts.events import MasterEvent
from appsecgate_master.storage import AggregateStore, MasterEventStore


def _state_dict(state: FindingState) -> dict[str, object]:
    """Все публичные поля (без служебного ``_last_event_type``, не в БД)."""
    return {k: v for k, v in asdict(state).items() if not k.startswith("_")}


async def test_db_rebuild_equals_pure_fold(
    events_store: MasterEventStore, aggregates_store: AggregateStore
):
    """Тот же поток событий: fold напрямую == rebuild через БД (полностью)."""
    events = prime("REOPENED") + [
        make_event("suppressed", scope="global", at=shift_at(BASE_AT, 10)),
        make_event("reopened", at=shift_at(BASE_AT, 11), branch="main", commit="cX"),
    ]
    expected = fold_events(events, project_key="proj", fp=FP)

    await events_store.ingest(events)
    await aggregates_store.rebuild()
    got = await aggregates_store.get_state("proj", FP)

    assert got is not None
    assert _state_dict(got) == _state_dict(expected)


def test_snapshot_events_parse_and_replay():
    """События в формате §3.3 парсятся (event/project_id) и replay корректен."""
    snapshot_lines = [
        {
            "event_id": "11111111-1111-4111-8111-111111111111",
            "client_event_id": "11111111-1111-4111-8111-111111111112",
            "event": "discovered",
            "project_id": "proj",
            "fp": FP,
            "severity": "high",
            "branch": "main",
            "commit": "c1",
            "at": "2026-10-31T12:00:00Z",
        },
        {
            "event_id": "11111111-1111-4111-8111-111111111113",
            "client_event_id": "11111111-1111-4111-8111-111111111114",
            "event": "not_found_in_scope",
            "project_id": "proj",
            "fp": FP,
            "branch": "main",
            "commit": "c2",
            "at": "2026-10-31T13:00:00Z",
            "missed_scan_count": 2,
        },
        {
            "event_id": "11111111-1111-4111-8111-111111111115",
            "client_event_id": "11111111-1111-4111-8111-111111111116",
            "event": "verify_fixed",
            "project_id": "proj",
            "fp": FP,
            "branch": "main",
            "commit": "c3",
            "at": "2026-10-31T14:00:00Z",
        },
    ]
    events = [MasterEvent.model_validate(line) for line in snapshot_lines]
    assert events[0].project_key == "proj"
    assert events[0].event_type.value == "discovered"

    state = fold_events(events, project_key="proj", fp=FP)
    assert state is not None
    assert state.status == "FIXED"
    assert state.severity == "high"
    assert state.missed_scan_count == 2
    assert state.verified_status == "fixed"


async def test_snapshot_events_through_db_match_pure_fold(
    events_store: MasterEventStore, aggregates_store: AggregateStore
):
    """Снапшот-события, прошедшие ingest+rebuild, дают тот же статус."""
    events = [
        MasterEvent.model_validate(
            {
                "event_id": "21111111-1111-4111-8111-111111111111",
                "client_event_id": "21111111-1111-4111-8111-111111111112",
                "event": "discovered",
                "project_id": "proj",
                "fp": FP,
                "at": "2026-10-31T12:00:00Z",
            }
        ),
        MasterEvent.model_validate(
            {
                "event_id": "21111111-1111-4111-8111-111111111113",
                "client_event_id": "21111111-1111-4111-8111-111111111114",
                "event": "verify_wont_fix",
                "project_id": "proj",
                "fp": FP,
                "note": "согласовано с командой",
                "at": "2026-10-31T12:05:00Z",
            }
        ),
    ]
    expected = fold_events(events, project_key="proj", fp=FP)
    assert expected is not None
    assert expected.status == "WONT_FIX"

    await events_store.ingest(events)
    await aggregates_store.rebuild()
    got = await aggregates_store.get_state("proj", FP)
    assert got is not None
    assert got.status == "WONT_FIX"
    assert _state_dict(got) == _state_dict(expected)
