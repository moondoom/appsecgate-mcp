"""Gate Engine — гейт-матрица ADR-0006 §2.3 (двойной контур).

Локально никогда не блокируем (максимум warn). В CI решение принимает
матрица §2.3: severity-гейт независим от статуса (кроме POTENTIALLY_FIXED,
которым управляет ``potentially_fixed_on_block_severity``), WONT_FIX
скипается только на своей ветке (``<unknown>`` → block), local-подавление
не скрывает (двойной контур).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from appsecgate_mcp.config.models import CiGateConfig, Config
from appsecgate_mcp.models.finding import Finding
from appsecgate_mcp.orchestration.shown_source import ShownRecord

UNKNOWN_BRANCH = "<unknown>"


class GateReason(StrEnum):
    """Причины решений gate (ADR-0006 §2.3)."""

    CI_SEVERITY = "ci_severity"
    UNRESOLVED_LOCAL = "unresolved_local"
    REOPENED = "reopened"
    UNCONFIRMED_FIX_CRITICAL = "unconfirmed_fix_critical"
    UNCONFIRMED_FIX = "unconfirmed_fix"
    FIXED = "fixed"
    SUPPRESSED = "suppressed"
    WONT_FIX = "wont_fix"
    WONT_FIX_OTHER_BRANCH = "wont_fix_other_branch"
    CI_NEW = "ci_new"
    LOCAL_WARN = "local_warn"
    LOCAL_INFO = "local_info"


def _severity_in(finding: Finding, values: list[str]) -> bool:
    wanted = {v.strip().lower() for v in values}
    return finding.severity.value.lower() in wanted


def _is_expired(expires_at: str | None) -> bool:
    """Истёк ли suppression по ``suppression_expires_at`` (ADR-0006 §2.2)."""
    if not expires_at:
        return False
    try:
        parsed = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= datetime.now(UTC)


def decide(
    finding: Finding,
    record: ShownRecord | None,
    *,
    cfg: CiGateConfig,
    branch: str | None,
) -> GateDecision:
    """Решение gate по строке матрицы §2.3 (ADR-0006) — таблица, не цепочка if.

    Строки проверяются по порядку, первое совпадение побеждает. ``branch`` —
    текущая ветка CI (``None``, если не определяется): тогда «своя ветка»
    для ``WONT_FIX`` не распознаётся и консервативно блокирует
    (правило ``<unknown>`` никогда не равен CI-branch).
    """
    status = record.gate_status if record is not None else None
    sev_block = _severity_in(finding, cfg.block_on)
    suppressed_valid = (
        record is not None
        and record.suppression_scope in ("ci", "global")
        and not _is_expired(record.suppression_expires_at)
    )
    same_branch = (
        branch is not None
        and branch != UNKNOWN_BRANCH
        and record is not None
        and record.last_seen_branch not in (None, UNKNOWN_BRANCH)
        and record.last_seen_branch == branch
    )
    pf_action = "block" if cfg.potentially_fixed_on_block_severity == "block" else "warn"

    table: list[tuple[bool, str, str]] = [
        # 4. POTENTIALLY_FIXED + block-severity — конфиг (Q2), до severity-гейта.
        (status == "POTENTIALLY_FIXED" and sev_block, pf_action, GateReason.UNCONFIRMED_FIX_CRITICAL),
        # 5. POTENTIALLY_FIXED + не-block-severity → warn.
        (status == "POTENTIALLY_FIXED", "warn", GateReason.UNCONFIRMED_FIX),
        # 1. severity-гейт независим от статуса (§2.2).
        (sev_block, "block", GateReason.CI_SEVERITY),
        # 2. SHOWN → «знал и не починил».
        (status == "SHOWN", "block", GateReason.UNRESOLVED_LOCAL),
        # 3. REOPENED → блок.
        (status == "REOPENED", "block", GateReason.REOPENED),
        # 6. FIXED → skip.
        (status == "FIXED", "skip", GateReason.FIXED),
        # 7. SUPPRESSED + ci/global + не истёк → skip.
        (suppressed_valid, "skip", GateReason.SUPPRESSED),
        # 8. SUPPRESSED + local + local_suppression_hides → skip.
        (
            status == "SUPPRESSED"
            and record is not None
            and record.suppression_scope == "local"
            and cfg.local_suppression_hides,
            "skip",
            GateReason.SUPPRESSED,
        ),
        # 9. SUPPRESSED + local (двойной контур) или истёкший ci/global → block.
        (status == "SUPPRESSED", "block", GateReason.UNRESOLVED_LOCAL),
        # 10. WONT_FIX + wont_fix_action=skip → skip.
        (status == "WONT_FIX" and cfg.wont_fix_action == "skip", "skip", GateReason.WONT_FIX),
        # 11. WONT_FIX + wont_fix_action=block → block.
        (status == "WONT_FIX" and cfg.wont_fix_action == "block", "block", GateReason.WONT_FIX),
        # 12. WONT_FIX + skip-if-same-branch + своя ветка → skip.
        (
            status == "WONT_FIX" and cfg.wont_fix_action == "skip-if-same-branch" and same_branch,
            "skip",
            GateReason.WONT_FIX,
        ),
        # 13. WONT_FIX + skip-if-same-branch + чужая/<unknown> ветка → block.
        (
            status == "WONT_FIX" and cfg.wont_fix_action == "skip-if-same-branch",
            "block",
            GateReason.WONT_FIX_OTHER_BRANCH,
        ),
    ]
    for cond, action, reason in table:
        if cond:
            return GateDecision(finding.fingerprint, action, reason)
    # 14. Нет записи → new_finding_action.
    return GateDecision(finding.fingerprint, cfg.new_finding_action, GateReason.CI_NEW)


@dataclass
class GateDecision:
    """Решение gate по одной находке."""

    fingerprint: str
    action: str  # block | warn | info | skip
    reason: str


@dataclass
class GateSummary:
    """Сводка решений gate по набору находок."""

    mode: str
    total: int = 0
    blocked: list[GateDecision] = field(default_factory=list)
    warned: list[GateDecision] = field(default_factory=list)
    informed: list[GateDecision] = field(default_factory=list)
    skipped: list[GateDecision] = field(default_factory=list)

    @property
    def block_count(self) -> int:
        return len(self.blocked)

    @property
    def skip_count(self) -> int:
        return len(self.skipped)

    @property
    def should_fail(self) -> bool:
        return bool(self.blocked)

    @property
    def by_reason(self) -> dict[str, int]:
        """Счётчики решений по reason (ADR-0006 §2.3) — для сводок CI."""
        counts: dict[str, int] = {}
        for decision in (*self.blocked, *self.warned, *self.informed, *self.skipped):
            counts[decision.reason] = counts.get(decision.reason, 0) + 1
        return counts


class GateEngine:
    """Оценивает находки по локальным и CI-правилам (ADR-0006 §2.3)."""

    def __init__(
        self,
        config: Config,
        *,
        shown_store=None,
        branch: str | None = None,
    ) -> None:
        self.config = config
        self.shown_store = shown_store
        # Текущая ветка CI для skip-if-same-branch (None — не определяется).
        self.branch = branch

    async def evaluate(self, finding: Finding, mode: str = "local") -> GateDecision:
        """Возвращает решение gate для одной находки."""
        if mode == "ci":
            record = await self._lookup_shown(finding.fingerprint)
            return decide(finding, record, cfg=self.config.gates.ci, branch=self.branch)
        return self._evaluate_local(finding)

    def _evaluate_local(self, finding: Finding) -> GateDecision:
        # Локально не блокируем НИКОГДА — максимум warn.
        if _severity_in(finding, self.config.gates.local.warn_on):
            return GateDecision(finding.fingerprint, "warn", GateReason.LOCAL_WARN)
        return GateDecision(finding.fingerprint, "info", GateReason.LOCAL_INFO)

    async def _lookup_shown(self, fingerprint: str) -> ShownRecord | None:
        """Возвращает ShownRecord находки из любого источника.

        Источник с ``record`` (snapshot, ADR-0003 §5.3) отвечает деталями;
        локальный ``ShownFindingsStore`` — через ``find`` (статус/ветка);
        минимальный ``was_shown`` (bool) — «был показан» → SHOWN.
        Ошибка источника не роняет gate: находка считается «не показанной».
        """
        store = self.shown_store
        if store is None:
            return None
        if hasattr(store, "record"):
            try:
                return await store.record(fingerprint)
            except Exception:
                return None
        if hasattr(store, "find"):
            try:
                row = await store.find(fingerprint)
            except Exception:
                return None
            if row is None:
                return None
            return ShownRecord(
                fingerprint=fingerprint,
                status=row.get("status"),
                last_seen_branch=row.get("last_seen_branch"),
            )
        try:
            shown = await store.was_shown(fingerprint)
        except Exception:
            return None
        return ShownRecord(fingerprint=fingerprint) if shown else None

    async def evaluate_all(
        self, findings: list[Finding], mode: str = "local"
    ) -> GateSummary:
        """Оценивает весь набор и агрегирует решения в `GateSummary`."""

        summary = GateSummary(mode=mode, total=len(findings))
        for finding in findings:
            decision = await self.evaluate(finding, mode)
            if decision.action == "block":
                summary.blocked.append(decision)
            elif decision.action == "warn":
                summary.warned.append(decision)
            elif decision.action == "skip":
                summary.skipped.append(decision)
            else:
                summary.informed.append(decision)
        return summary
