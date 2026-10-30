"""Gate Engine — двойной контур gates.

Локально никогда не блокируем (максимум warn). В CI блокируем по severity,
а также находки, которые были показаны локально и не закрыты
(`block_on_unresolved_local`) — killer-feature «ты знал и не починил».
"""

from __future__ import annotations

from dataclasses import dataclass, field

from appsecgate_mcp.config.models import Config
from appsecgate_mcp.models.finding import Finding
from appsecgate_mcp.orchestration.shown_source import ShownRecord


@dataclass
class GateDecision:
    """Решение gate по одной находке."""

    fingerprint: str
    action: str  # block | warn | info
    reason: str


@dataclass
class GateSummary:
    """Сводка решений gate по набору находок."""

    mode: str
    total: int = 0
    blocked: list[GateDecision] = field(default_factory=list)
    warned: list[GateDecision] = field(default_factory=list)
    informed: list[GateDecision] = field(default_factory=list)

    @property
    def block_count(self) -> int:
        return len(self.blocked)

    @property
    def should_fail(self) -> bool:
        return bool(self.blocked)


class GateEngine:
    """Оценивает находки по локальным и CI-правилам."""

    def __init__(self, config: Config, *, shown_store=None) -> None:
        self.config = config
        self.shown_store = shown_store

    @staticmethod
    def _matches(finding: Finding, values: list[str]) -> bool:
        wanted = {v.strip().lower() for v in values}
        return finding.severity.value.lower() in wanted

    async def evaluate(self, finding: Finding, mode: str = "local") -> GateDecision:
        """Возвращает решение gate для одной находки."""
        if mode == "ci":
            return await self._evaluate_ci(finding)
        return self._evaluate_local(finding)

    def _evaluate_local(self, finding: Finding) -> GateDecision:
        # Локально не блокируем НИКОГДА — максимум warn.
        if self._matches(finding, self.config.gates.local.warn_on):
            return GateDecision(finding.fingerprint, "warn", "local_warn")
        return GateDecision(finding.fingerprint, "info", "local_info")

    async def _evaluate_ci(self, finding: Finding) -> GateDecision:
        ci = self.config.gates.ci
        if self._matches(finding, ci.block_on):
            return GateDecision(finding.fingerprint, "block", "ci_severity")
        if ci.block_on_unresolved_local and self.shown_store is not None:
            shown = await self._lookup_shown(finding.fingerprint)
            if shown is not None and not self._resolved_in_ci(shown):
                reason = "wont_fix" if shown.verified_status == "wont_fix" else "unresolved_local"
                return GateDecision(finding.fingerprint, "block", reason)
        if self._matches(finding, ci.warn_on):
            return GateDecision(finding.fingerprint, "warn", "ci_warn")
        return GateDecision(finding.fingerprint, "info", "ci_info")

    async def _lookup_shown(self, fingerprint: str) -> ShownRecord | None:
        """Возвращает запись о показанной находке из любого источника.

        Локальный ``shown_store`` отвечает через ``was_shown`` (bool),
        snapshot-источник (ADR-0003 §5.3) — через ``record`` (детали).
        Ошибка источника не роняет gate: находка считается «не показанной».
        """
        store = self.shown_store
        if hasattr(store, "record"):
            try:
                return await store.record(fingerprint)
            except Exception:
                return None
        try:
            shown = await store.was_shown(fingerprint)
        except Exception:
            return None
        return ShownRecord(fingerprint=fingerprint) if shown else None

    @staticmethod
    def _resolved_in_ci(shown: ShownRecord) -> bool:
        """«Закрытая» находка в CI (ADR-0003 §5.2): fixed или suppression ci/global.

        Scope ``local`` и статус ``not_fixed``/``wont_fix`` блок НЕ снимают —
        это и есть двойной контур «знал и не починил».
        """
        if shown.verified_status == "fixed":
            return True
        if shown.suppression_scope in ("ci", "global"):
            return True
        return False

    async def evaluate_all(self, findings: list[Finding], mode: str = "local") -> GateSummary:
        """Оценивает весь набор и агрегирует решения в `GateSummary`."""

        summary = GateSummary(mode=mode, total=len(findings))
        for finding in findings:
            decision = await self.evaluate(finding, mode)
            if decision.action == "block":
                summary.blocked.append(decision)
            elif decision.action == "warn":
                summary.warned.append(decision)
            else:
                summary.informed.append(decision)
        return summary
