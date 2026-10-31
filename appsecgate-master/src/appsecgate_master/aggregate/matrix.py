"""Матрица переходов жизненного цикла находки (ADR-0006 §2.1).

Строки — предыдущий статус (None = находки ещё не было), столбцы — событие.
Ячейка «—» в матрице = no-op: событие записывается, состояние не меняется.
TRANSITIONS содержит только непустые ячейки матрицы.

Дополнения из §3.4 (конфликт-резолюция):
- FIXED + reopened → REOPENED (правило 2: reopened побеждает FIXED,
  positive-merge поверх FIXED приходит событием reopened).
- SUPPRESSED + reopened → REOPENED (правило 3: suppressed(ci/global) побеждает
  всё, кроме reopened после него — новый цикл).

Инвариант: каждый реальный переход обновляет status_updated_at.
"""

from __future__ import annotations

from appsecgate_master.contracts.events import EventType

# Статусы, на которых negative-merge (not_found_in_scope) не меняет статус
# (инвариант ADR-0006 §2.1: not_found_in_scope не применяется к FIXED/SUPPRESSED/WONT_FIX).
TERMINAL_NOOP: frozenset[str] = frozenset({"FIXED", "SUPPRESSED", "WONT_FIX"})

# verify_* на WONT_FIX — no-op (инвариант §2.1).
WONT_FIX_NOOP: frozenset[EventType] = frozenset(
    {EventType.VERIFY_FIXED, EventType.VERIFY_NOT_FIXED, EventType.VERIFY_WONT_FIX}
)

TRANSITIONS: dict[tuple[str | None, EventType], str] = {
    # (None) — находка без состояния.
    (None, EventType.DISCOVERED): "SHOWN",
    (None, EventType.SUPPRESSED): "SUPPRESSED",
    # SHOWN
    ("SHOWN", EventType.REAFFIRMED): "SHOWN",
    ("SHOWN", EventType.NOT_FOUND_IN_SCOPE): "POTENTIALLY_FIXED",
    ("SHOWN", EventType.VERIFY_NOT_FIXED): "SHOWN",
    ("SHOWN", EventType.VERIFY_WONT_FIX): "WONT_FIX",
    ("SHOWN", EventType.SUPPRESSED): "SUPPRESSED",
    # POTENTIALLY_FIXED
    ("POTENTIALLY_FIXED", EventType.REAFFIRMED): "SHOWN",
    ("POTENTIALLY_FIXED", EventType.NOT_FOUND_IN_SCOPE): "POTENTIALLY_FIXED",
    ("POTENTIALLY_FIXED", EventType.VERIFY_FIXED): "FIXED",
    ("POTENTIALLY_FIXED", EventType.VERIFY_NOT_FIXED): "POTENTIALLY_FIXED",
    ("POTENTIALLY_FIXED", EventType.VERIFY_WONT_FIX): "WONT_FIX",
    ("POTENTIALLY_FIXED", EventType.SUPPRESSED): "SUPPRESSED",
    # FIXED
    ("FIXED", EventType.REAFFIRMED): "REOPENED",
    ("FIXED", EventType.NOT_FOUND_IN_SCOPE): "FIXED",
    ("FIXED", EventType.SUPPRESSED): "SUPPRESSED",
    ("FIXED", EventType.REOPENED): "REOPENED",  # правило 2 §3.4
    # REOPENED
    ("REOPENED", EventType.REAFFIRMED): "REOPENED",
    ("REOPENED", EventType.NOT_FOUND_IN_SCOPE): "POTENTIALLY_FIXED",
    ("REOPENED", EventType.VERIFY_FIXED): "FIXED",
    ("REOPENED", EventType.VERIFY_NOT_FIXED): "REOPENED",
    ("REOPENED", EventType.VERIFY_WONT_FIX): "WONT_FIX",
    ("REOPENED", EventType.SUPPRESSED): "SUPPRESSED",
    # SUPPRESSED
    ("SUPPRESSED", EventType.SUPPRESSION_EXPIRED): "SHOWN",
    ("SUPPRESSED", EventType.UNSUPPRESSED): "SHOWN",
    ("SUPPRESSED", EventType.REOPENED): "REOPENED",  # правило 3 §3.4
    # WONT_FIX
    ("WONT_FIX", EventType.SUPPRESSED): "SUPPRESSED",
    ("WONT_FIX", EventType.UNSUPPRESSED): "SHOWN",
}
