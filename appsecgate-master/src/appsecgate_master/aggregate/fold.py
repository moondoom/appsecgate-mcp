"""Fold событий в состояние агрегата (ADR-0006 §3.4).

Алгоритм (шаги §3.3 + §3.4):
1. Сортировка по (at, event_id|client_event_id) — правило 5 (LWW по UTC,
   tie-break по id).
2. Применение матрицы §2.1 (TRANSITIONS). Ячейка «—» = no-op: наблюдения
   (severity, last_seen_*) обновляются, статус не меняется.
3. Конфликт-резолюция правил 1–4, 6:
   - Правило 1/2: verify_fixed проигрывает более позднему positive-merge в той
     же ветке (матрица: FIXED+reaffirmed/reopened → REOPENED); reopened
     побеждает FIXED (правило 2, доп. переход в матрице).
   - Правило 3: suppressed(ci/global) — SUPPRESSED; исключение — reopened
     после него (новый цикл, доп. переход в матрице).
   - Правило 4: suppressed(local) сохраняет SUPPRESSED, но affects_ci=False.
   - Правило 6: WONT_FIX терминален до unsuppressed (матрица: WONT_FIX
     переходит только через suppressed/unsuppressed).
"""

from __future__ import annotations

from collections.abc import Sequence

from appsecgate_master.aggregate.matrix import TRANSITIONS
from appsecgate_master.aggregate.state import CI_AFFECTING_SCOPES, FindingState
from appsecgate_master.contracts.events import EventType, MasterEvent

# События, увеличивающие scan_count (positive-merge).
_POSITIVE_MERGE: frozenset[EventType] = frozenset(
    {EventType.DISCOVERED, EventType.REAFFIRMED, EventType.REOPENED}
)


def fold_events(events: Sequence[MasterEvent], *, project_key: str, fp: str) -> FindingState | None:
    """Пересчитать состояние (project_key, fp) из событий.

    Возвращает None, если событий нет (находка никогда не наблюдалась).
    Порядок детерминирован: (at, event_id|client_event_id) — правило 5 §3.4.
    """
    if not events:
        return None
    state = FindingState(project_key=project_key, fp=fp)
    for event in sorted(events, key=MasterEvent.sort_key):
        apply_event(state, event)
    return state


def apply_event(state: FindingState, event: MasterEvent) -> None:
    """Применить одно событие: наблюдения всегда, переход только по матрице."""
    event_type = event.event_type
    _update_observations(state, event)

    new_status = TRANSITIONS.get((state.status, event_type))
    if new_status is None:
        return  # ячейка «—»: no-op

    state.status = new_status
    state.status_updated_at = event.at
    state._last_event_type = event_type.value

    if event_type in _POSITIVE_MERGE:
        state.scan_count += 1
    if event_type is EventType.NOT_FOUND_IN_SCOPE and event.missed_scan_count is not None:
        state.missed_scan_count = event.missed_scan_count
    if event_type is EventType.SUPPRESSED:
        # Правила 3/4 §3.4: scope ci/global влияет на CI, local — только хранится.
        state.suppression_scope = event.scope
        state.suppression_expires_at = event.expires_at
        state.suppressed_at = event.at
        state.suppress_reason = event.reason
        state.affects_ci = event.scope in CI_AFFECTING_SCOPES
    if event_type in (EventType.SUPPRESSION_EXPIRED, EventType.UNSUPPRESSED):
        state.suppression_scope = None
        state.suppression_expires_at = None
        state.suppressed_at = None
        state.suppress_reason = None
        state.affects_ci = True
    if event_type is EventType.REOPENED:
        # Правило 3 §3.4: reopened после suppressed — новый цикл, подавление снято.
        state.suppression_scope = None
        state.suppression_expires_at = None
        state.suppressed_at = None
        state.suppress_reason = None
        state.affects_ci = True
    if event_type is EventType.UNSUPPRESSED:
        state.wont_fix_at = None
        state.wont_fix_reason = None
    if event_type is EventType.VERIFY_FIXED:
        state.verified_status = "fixed"
        state.verified_at = event.at
    if event_type is EventType.VERIFY_NOT_FIXED:
        state.verified_status = "not_fixed"
        state.verified_at = event.at
    if event_type is EventType.VERIFY_WONT_FIX:
        state.verified_status = "wont_fix"
        state.verified_at = event.at
        state.wont_fix_at = event.at
        state.wont_fix_reason = event.note


def _update_observations(state: FindingState, event: MasterEvent) -> None:
    """Обновить наблюдаемые поля независимо от перехода в матрице."""
    if event.severity:
        state.severity = event.severity

    if event.last_seen_branch:
        state.last_seen_branch = event.last_seen_branch
        state.last_seen_commit = event.last_seen_commit
    elif event.branch:
        state.last_seen_branch = event.branch
        state.last_seen_commit = event.commit

    if event.first_seen_branch:
        state.first_seen_branch = event.first_seen_branch
        state.first_seen_commit = event.first_seen_commit

    if event.event_type is EventType.DISCOVERED:
        if state.first_seen_at is None:
            state.first_seen_at = event.at
            if state.first_seen_branch is None:
                state.first_seen_branch = state.last_seen_branch
            if state.first_seen_commit is None:
                state.first_seen_commit = state.last_seen_commit

    # last_seen_at — только для finding-событий, описывающих наблюдение.
    if event.event_type in (
        EventType.DISCOVERED,
        EventType.REAFFIRMED,
        EventType.REOPENED,
        EventType.NOT_FOUND_IN_SCOPE,
        EventType.VERIFY_FIXED,
        EventType.VERIFY_NOT_FIXED,
        EventType.VERIFY_WONT_FIX,
    ):
        state.last_seen_at = event.at
