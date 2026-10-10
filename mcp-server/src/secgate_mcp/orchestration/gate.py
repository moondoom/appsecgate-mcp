"""Gate Engine — двойной контур gates.

Локально никогда не блокируем (максимум warn). В CI блокируем по severity,
а также находки, которые были показаны локально и не закрыты
(`block_on_unresolved_local`) — killer-feature «ты знал и не починил».
"""

from __future__ import annotations

from dataclasses import dataclass, field

from secgate_mcp.config.models import Config
from secgate_mcp.models.finding import Finding


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
            try:
                if await self.shown_store.was_shown(finding.fingerprint):
                    return GateDecision(finding.fingerprint, "block", "unresolved_local")
            except Exception:
                pass
        if self._matches(finding, ci.warn_on):
            return GateDecision(finding.fingerprint, "warn", "ci_warn")
        return GateDecision(finding.fingerprint, "info", "ci_info")

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
