"""Auto-Fixer — уровень 0 воронки эскалации.

Пытается исправить находку до показа разработчику. Фаза 1 поддерживает
стратегию `patch` (готовый патч из метаданных сканера) и заглушку
`suggestion` (LLM-подсказка появится в следующих фазах).
"""

from __future__ import annotations

from secgate_mcp.config.models import Config
from secgate_mcp.models.finding import Finding, FixResult


class AutoFixer:
    """Пытается автоматически исправить находку."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config

    async def fix(self, finding: Finding, strategy: str = "patch") -> FixResult:
        """Возвращает `FixResult` для находки по стратегии."""
        finding_id = finding.display_id()

        if self.config is not None and not self.config.auto_fix.enabled:
            return FixResult(finding_id=finding_id, status="skipped", reason="auto_fix disabled")

        if strategy == "patch":
            patch = finding.generate_patch()
            if patch:
                return FixResult(finding_id=finding_id, status="patched", patch=patch)
            return FixResult(
                finding_id=finding_id, status="failed", reason="no known patch available"
            )

        if strategy == "suggestion":
            # LLM-подсказки не реализованы в Фазе 1 (нужен локальный LLM).
            return FixResult(
                finding_id=finding_id,
                status="skipped",
                reason="LLM suggestion is not available in Phase 1",
            )

        return FixResult(
            finding_id=finding_id, status="failed", reason=f"unknown strategy: {strategy}"
        )
