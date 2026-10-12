"""ConfigSuppressFilter — подавление находок по правилам из `config.suppress`.

Фильтр шума на уровне конфигурации. Разработчик декларирует в `config.suppress`
правила вида `rule` + `paths`, и находки, подпадающие под них, отбрасываются
до попадания в `shown_store` и in-memory реестр.

Семантика сопоставления:
- `rule` — подстрока `finding.rule_id` (case-sensitive):
  `generic.secrets` подавляет `semgrep.generic.secrets`.
- `paths` — glob-шаблоны, применяемые к относительному POSIX-пути находки.
  `*` матчит в пределах одного сегмента, `**` пересекает границы каталогов.
  Пустой `paths` — правило применяется ко всем файлам с подходящим `rule_id`.
- `scope` — в Фазе 1 игнорируется (CI-контура ещё нет): применяются все правила.
"""

from __future__ import annotations

import fnmatch

from appsecgate_mcp.config.models import Config, SuppressRuleConfig
from appsecgate_mcp.models.finding import Finding


def _glob_match(path: str, pattern: str) -> bool:
    """Сегментно-осознанный glob по POSIX-путю.

    `*`/`?`/`[seq]` матчат только внутри одного сегмента (между `/`),
    `**` матчит ноль и более сегментов, пересекая `/`. Это отличается от
    голого ``fnmatch.fnmatch``, где ``*`` по умолчанию пересекает ``/``.
    """
    path_parts = path.split("/")
    spec_parts = pattern.split("/")
    return _match_segments(path_parts, spec_parts)


def _match_segments(path: list[str], spec: list[str], pi: int = 0, si: int = 0) -> bool:
    """Backtracking-матчер сегментов: `**` — ноль и более сегментов пути."""
    while si < len(spec):
        segment = spec[si]
        if segment == "**":
            # `**` может съесть текущий сегмент пути или ноль сегментов.
            if _match_segments(path, spec, pi, si + 1):
                return True
            if pi < len(path):
                return _match_segments(path, spec, pi + 1, si)
            return False
        if pi >= len(path):
            return False
        if not fnmatch.fnmatch(path[pi], segment):
            return False
        pi += 1
        si += 1
    return pi == len(path)


class ConfigSuppressFilter:
    """Отбрасывает находки, подпадающие под правила `config.suppress`."""

    def __init__(self, config: Config) -> None:
        self.suppress = list(getattr(config, "suppress", []) or [])

    def apply(self, findings: list[Finding]) -> list[Finding]:
        """Возвращает находки, не подпадающие ни под одно suppress-правило."""
        if not self.suppress:
            return findings
        return [f for f in findings if not self._suppressed(f)]

    def _suppressed(self, finding: Finding) -> bool:
        return any(self._matches(rule, finding) for rule in self.suppress)

    @staticmethod
    def _matches(rule: SuppressRuleConfig, finding: Finding) -> bool:
        if not rule.rule:
            return False
        if rule.rule not in finding.rule_id:
            return False
        if not rule.paths:
            return True
        return any(_glob_match(finding.file_path, pattern) for pattern in rule.paths)
