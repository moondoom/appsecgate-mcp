"""Состояние находки на master — результат fold событий (ADR-0006 §1.3/§3.4).

Статусы: SHOWN, POTENTIALLY_FIXED, FIXED, REOPENED, SUPPRESSED, WONT_FIX.
Вердикт CI по правилу 4 §3.4: suppressed(local) хранится, но не влияет на CI
(affects_ci=False); ci/global — влияют (True).
"""

from __future__ import annotations

from dataclasses import dataclass, field

STATUSES: tuple[str, ...] = (
    "SHOWN",
    "POTENTIALLY_FIXED",
    "FIXED",
    "REOPENED",
    "SUPPRESSED",
    "WONT_FIX",
)

# Scope suppression, влияющие на CI-вердикт (правило 3/4 §3.4).
CI_AFFECTING_SCOPES: frozenset[str] = frozenset({"ci", "global"})


@dataclass(slots=True)
class FindingState:
    """Текущее состояние агрегата (project_key, fp)."""

    project_key: str
    fp: str
    status: str | None = None  # None — находка ни разу не была positive-merge
    severity: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    first_seen_branch: str | None = None
    first_seen_commit: str | None = None
    last_seen_branch: str | None = None
    last_seen_commit: str | None = None
    # Счётчики для gate (negative-merge = пропуск, positive-merge = находка).
    scan_count: int = 0
    missed_scan_count: int = 0
    # Suppression (scope: local|ci|global).
    suppression_scope: str | None = None
    suppression_expires_at: str | None = None
    suppressed_at: str | None = None
    suppress_reason: str | None = None
    affects_ci: bool = True  # правило 4: suppressed(local) → False
    # WONT_FIX (правило 6: терминален до unsuppressed).
    wont_fix_at: str | None = None
    wont_fix_reason: str | None = None
    # verify_* вердикты.
    verified_status: str | None = None
    verified_at: str | None = None
    status_updated_at: str | None = None
    # Служебное: событие, выполнившее последний переход.
    _last_event_type: str | None = field(default=None, repr=False)

    @property
    def suppression_affects_ci(self) -> bool:
        """Вердикт CI по правилу 4 §3.4."""
        return self.suppression_scope in CI_AFFECTING_SCOPES
