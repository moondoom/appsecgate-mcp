"""Матрица переходов §2.1: каждая непустая ячейка + no-op («—») + инварианты."""

from __future__ import annotations

import pytest
from helpers import BASE_AT, FP, make_event, prime, primed_state, shift_at

from appsecgate_master.aggregate.fold import apply_event, fold_events
from appsecgate_master.aggregate.matrix import TERMINAL_NOOP, TRANSITIONS, WONT_FIX_NOOP
from appsecgate_master.aggregate.state import FindingState

# Обязательные атрибуты для событий с требованиями (схема §1.4).
_EVENT_EXTRAS = {
    "suppressed": {"scope": "local"},
    "verify_wont_fix": {"note": "не планируется"},
    "unsuppressed": {"note": "снято"},
}


def _apply_extra(state: FindingState, event_type: str) -> FindingState:
    """Применить одно событие к состоянию (с переходом в заданный at)."""
    apply_event(
        state,
        make_event(
            event_type, fp=FP, at=shift_at(BASE_AT, 99), **_EVENT_EXTRAS.get(event_type, {})
        ),
    )
    return state


@pytest.mark.parametrize(
    ("prev", "event_type", "expected"),
    sorted(
        ((prev, ev.value, expected) for (prev, ev), expected in TRANSITIONS.items()),
        key=lambda item: (item[0] or "", item[1]),
    ),
)
def test_matrix_nonempty_cells(prev: str | None, event_type: str, expected: str):
    if prev is None:
        state = FindingState(project_key="proj", fp=FP)
    else:
        state, _ = primed_state(prev)
    _apply_extra(state, event_type)
    assert state.status == expected


def test_discovered_on_empty_is_shown_and_noop_after():
    events = [make_event("discovered"), make_event("discovered", at=shift_at(BASE_AT, 5))]
    state = fold_events(events, project_key="proj", fp=FP)
    assert state is not None
    assert state.status == "SHOWN"
    assert state.scan_count == 1  # второй discovered на SHOWN — no-op, счётчик не растёт


@pytest.mark.parametrize("event_type", sorted(e.value for e in WONT_FIX_NOOP))
def test_verify_on_wont_fix_is_noop(event_type: str):
    state, _ = primed_state("WONT_FIX")
    _apply_extra(state, event_type)
    assert state.status == "WONT_FIX"


@pytest.mark.parametrize("status", sorted(TERMINAL_NOOP))
def test_not_found_in_scope_on_terminal_is_noop(status: str):
    state, _ = primed_state(status)
    _apply_extra(state, "not_found_in_scope")
    assert state.status == status


def test_suppression_lifecycle_matrix():
    """SUPPRESSED→SHOWN только через suppression_expired/unsuppressed."""
    state, _ = primed_state("SUPPRESSED")
    for event_type in ("reaffirmed", "not_found_in_scope", "verify_fixed"):
        _apply_extra(state, event_type)
        assert state.status == "SUPPRESSED"
    _apply_extra(state, "suppression_expired")
    assert state.status == "SHOWN"
    _apply_extra(state, "suppressed")
    assert state.status == "SUPPRESSED"
    _apply_extra(state, "unsuppressed")
    assert state.status == "SHOWN"


def test_transition_updates_status_updated_at():
    state, _ = primed_state("SHOWN")
    event = make_event("not_found_in_scope", at="2026-10-31T13:00:00Z")
    apply_event(state, event)
    assert state.status_updated_at == "2026-10-31T13:00:00Z"


def test_noop_keeps_status_updated_at():
    state, _ = primed_state("WONT_FIX")
    before = state.status_updated_at
    _apply_extra(state, "verify_fixed")
    assert state.status == "WONT_FIX"
    assert state.status_updated_at == before


def test_full_lifecycle_fold():
    """discovered → pf → verify_fixed → reopened → pf → verify_fixed."""
    events = prime("REOPENED")
    events += [
        make_event("not_found_in_scope", at=shift_at(BASE_AT, 10)),
        make_event("verify_fixed", at=shift_at(BASE_AT, 11)),
    ]
    state = fold_events(events, project_key="proj", fp=FP)
    assert state is not None
    assert state.status == "FIXED"
    assert state.scan_count == 2  # discovered + reopened
    assert state.verified_status == "fixed"
