"""Конфликт-резолюция ADR-0006 §3.4: правила 1–6 на агрегате."""

from __future__ import annotations

from helpers import BASE_AT, FP, make_event, prime, primed_state, shift_at

from appsecgate_master.aggregate.fold import fold_events


def test_rule1_verify_fixed_wins_over_earlier_negative_same_branch():
    """verify_fixed позже not_found_in_scope в той же ветке → FIXED (правило 1)."""
    events = prime("POTENTIALLY_FIXED")
    events.append(
        make_event("verify_fixed", at=shift_at(BASE_AT, 10), branch="feature/x", commit="c2")
    )
    state = fold_events(events, project_key="proj", fp=FP)
    assert state is not None
    assert state.status == "FIXED"
    assert state.verified_status == "fixed"


def test_rule1_reaffirmed_after_verify_fixed_same_branch_reopens():
    """reaffirmed с более новым commit в той же ветке перебивает verify_fixed."""
    events = prime("FIXED")
    events.append(
        make_event(
            "reaffirmed",
            at=shift_at(BASE_AT, 10),
            branch="feature/x",
            commit="c3",
            last_seen_branch="feature/x",
            last_seen_commit="c3",
        )
    )
    state = fold_events(events, project_key="proj", fp=FP)
    assert state is not None
    assert state.status == "REOPENED"


def test_rule2_reopened_wins_over_fixed():
    """positive-merge поверх FIXED → REOPENED (правило 2)."""
    events = prime("FIXED")
    events.append(make_event("reopened", at=shift_at(BASE_AT, 10), branch="main", commit="c9"))
    state = fold_events(events, project_key="proj", fp=FP)
    assert state is not None
    assert state.status == "REOPENED"
    assert state.scan_count == 2


def test_rule3_suppressed_ci_beats_everything():
    """suppressed(ci) → SUPPRESSED; positive/negative/verify не меняют (правило 3)."""
    state, events = primed_state("SHOWN")
    state = fold_events(
        events
        + [
            make_event("suppressed", scope="ci", at=shift_at(BASE_AT, 5), reason="CI-решение"),
            make_event("reaffirmed", at=shift_at(BASE_AT, 6)),
            make_event("not_found_in_scope", at=shift_at(BASE_AT, 7)),
            make_event("verify_fixed", at=shift_at(BASE_AT, 8)),
        ],
        project_key="proj",
        fp=FP,
    )
    assert state is not None
    assert state.status == "SUPPRESSED"
    assert state.suppression_scope == "ci"
    assert state.affects_ci is True
    assert state.suppression_affects_ci is True


def test_rule3_reopened_after_suppression_new_cycle():
    """reopened после suppressed — новый цикл: SUPPRESSED → REOPENED (правило 3)."""
    state, events = primed_state("SHOWN")
    state = fold_events(
        events
        + [
            make_event("suppressed", scope="global", at=shift_at(BASE_AT, 5)),
            make_event("reopened", at=shift_at(BASE_AT, 6), branch="main", commit="c10"),
        ],
        project_key="proj",
        fp=FP,
    )
    assert state is not None
    assert state.status == "REOPENED"
    assert state.suppression_scope is None
    assert state.affects_ci is True


def test_rule4_suppressed_local_does_not_affect_ci():
    """suppressed(local) хранится, но affects_ci=False (правило 4)."""
    state, events = primed_state("SHOWN")
    state = fold_events(
        events + [make_event("suppressed", scope="local", at=shift_at(BASE_AT, 5))],
        project_key="proj",
        fp=FP,
    )
    assert state is not None
    assert state.status == "SUPPRESSED"
    assert state.suppression_scope == "local"
    assert state.affects_ci is False
    assert state.suppression_affects_ci is False
    assert state.suppression_expires_at is None


def test_rule4_unsuppressed_restores_ci_verdict():
    state, events = primed_state("SUPPRESSED")
    state = fold_events(
        events
        + [
            make_event(
                "unsuppressed", at=shift_at(BASE_AT, 6), note="ошибка — снимаем local-подавление"
            )
        ],
        project_key="proj",
        fp=FP,
    )
    assert state is not None
    assert state.status == "SHOWN"
    assert state.affects_ci is True


def test_rule5_lww_later_at_wins_in_same_branch():
    """Позже по at — сильнее (LWW): reaffirmed после verify_fixed → REOPENED."""
    events = prime("FIXED")
    events.append(make_event("reaffirmed", at=shift_at(BASE_AT, 5), branch="feature/x"))
    state = fold_events(events, project_key="proj", fp=FP)
    assert state is not None
    assert state.status == "REOPENED"


def test_rule5_tie_break_by_event_id_deterministic():
    """Равные at: исход детерминирован по (event_id|client_event_id)."""
    base = [make_event("discovered"), make_event("not_found_in_scope", at=shift_at(BASE_AT, 1))]
    low_id = "00000000-0000-4000-8000-000000000001"
    high_id = "00000000-0000-4000-8000-000000000002"
    same_at = shift_at(BASE_AT, 2)

    # reaffirmed (id=1) раньше not_found (id=2): PF→SHOWN, затем SHOWN→PF.
    first = fold_events(
        base
        + [
            make_event("reaffirmed", at=same_at, client_event_id=low_id),
            make_event("not_found_in_scope", at=same_at, client_event_id=high_id),
        ],
        project_key="proj",
        fp=FP,
    )
    assert first is not None
    assert first.status == "POTENTIALLY_FIXED"

    # Порядок id обратный → not_found раньше reaffirmed → SHOWN.
    second = fold_events(
        base
        + [
            make_event("reaffirmed", at=same_at, client_event_id=high_id),
            make_event("not_found_in_scope", at=same_at, client_event_id=low_id),
        ],
        project_key="proj",
        fp=FP,
    )
    assert second is not None
    assert second.status == "SHOWN"


def test_rule6_wont_fix_terminal_until_unsuppressed():
    """WONT_FIX: verify/reaffirm/not_found не меняют; unsuppressed → SHOWN."""
    state, events = primed_state("WONT_FIX")
    state = fold_events(
        events
        + [
            make_event("verify_fixed", at=shift_at(BASE_AT, 5)),
            make_event("reaffirmed", at=shift_at(BASE_AT, 6)),
            make_event("not_found_in_scope", at=shift_at(BASE_AT, 7)),
        ],
        project_key="proj",
        fp=FP,
    )
    assert state is not None
    assert state.status == "WONT_FIX"
    assert state.wont_fix_reason == "wont fix: согласовано с командой"

    state = fold_events(
        events + [make_event("unsuppressed", at=shift_at(BASE_AT, 10), note="снято")],
        project_key="proj",
        fp=FP,
    )
    assert state is not None
    assert state.status == "SHOWN"
    assert state.wont_fix_at is None
    assert state.wont_fix_reason is None


def test_missed_scan_count_recorded():
    events = prime("POTENTIALLY_FIXED")
    events.append(make_event("not_found_in_scope", at=shift_at(BASE_AT, 10), missed_scan_count=4))
    state = fold_events(events, project_key="proj", fp=FP)
    assert state is not None
    assert state.missed_scan_count == 4


def test_last_seen_tracking():
    events = prime("SHOWN")
    events.append(make_event("reaffirmed", at=shift_at(BASE_AT, 10), branch="main", commit="c7"))
    state = fold_events(events, project_key="proj", fp=FP)
    assert state is not None
    assert state.first_seen_at == BASE_AT
    assert state.last_seen_at == shift_at(BASE_AT, 10)
    assert state.last_seen_branch == "main"
    assert state.last_seen_commit == "c7"


def test_empty_events_yield_none():
    assert fold_events([], project_key="proj", fp=FP) is None


def test_config_policy_ignored_by_fold():
    """config_policy не участвует в агрегате находок."""
    policy = make_event("config_policy", fp=None)
    state = fold_events([make_event("discovered"), policy], project_key="proj", fp=FP)
    assert state is not None
    assert state.status == "SHOWN"


def test_states_are_isolated_per_project_and_fp():
    a = fold_events(prime("SHOWN", project_key="p1", fp="fp-1"), project_key="p1", fp="fp-1")
    b = fold_events(prime("WONT_FIX", project_key="p2", fp="fp-1"), project_key="p2", fp="fp-1")
    assert a is not None and b is not None
    assert a.status == "SHOWN"
    assert b.status == "WONT_FIX"
