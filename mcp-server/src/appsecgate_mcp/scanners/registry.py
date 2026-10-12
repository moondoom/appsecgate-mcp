"""Реестр адаптеров сканеров.

Собирает доступные адаптеры по конфигурации проекта и предоставляет
координатору единый доступ к ним. Реестр ничего не запускает — он только
хранит и выдаёт адаптеры, чтобы оркестрация оставалась тонкой.
"""

from __future__ import annotations

from collections.abc import Iterator

from appsecgate_mcp.config.models import Config, ScannerConfig
from appsecgate_mcp.rules import ResolvedRules
from appsecgate_mcp.scanners.base import BaseScanner

# Какие инструменты какому адаптеру соответствуют (по полю `tool` в конфиге).
_TOOL_NAMES: dict[str, str] = {
    "semgrep": "semgrep",
    "gitleaks": "gitleaks",
    "trufflehog": "trufflehog",
    "trivy": "trivy",
}

# Инструмент по умолчанию для категории, если в конфиге `tool` не задан.
_DEFAULT_TOOL_BY_CATEGORY: dict[str, str] = {
    "sast": "semgrep",
    "secrets": "gitleaks",
    "sca": "trivy",
    "iac": "trivy",
}

_CATEGORY_FIELDS: tuple[str, ...] = ("sast", "secrets", "sca", "iac")


def _build_adapter(
    tool: str,
    *,
    project_path: str,
    timeout: float,
    config: ScannerConfig,
    resolved_rules: ResolvedRules | None = None,
):
    """Лениво импортирует и создаёт адаптер для инструмента.

    Ленивый импорт разрывает потенциальные циклы (адаптеры импортируют
    `base`, `base` импортирует `normalization`, регистр импортирует адаптеры).
    Resolved-правила прокидываются в адаптеры, которым нужен путь к правилам
    (semgrep/gitleaks/trufflehog); trivy правил-файлов не имеет.
    """
    if tool == "semgrep":
        from appsecgate_mcp.scanners.semgrep import SemgrepAdapter

        return SemgrepAdapter(
            project_path=project_path,
            timeout=timeout,
            config=config,
            resolved_rules=resolved_rules,
        )
    if tool == "gitleaks":
        from appsecgate_mcp.scanners.gitleaks import GitleaksAdapter

        return GitleaksAdapter(
            project_path=project_path,
            timeout=timeout,
            config=config,
            resolved_rules=resolved_rules,
        )
    if tool == "trufflehog":
        from appsecgate_mcp.scanners.trufflehog import TruffleHogAdapter

        return TruffleHogAdapter(
            project_path=project_path,
            timeout=timeout,
            config=config,
            resolved_rules=resolved_rules,
        )
    if tool == "trivy":
        from appsecgate_mcp.scanners.trivy import TrivyAdapter

        return TrivyAdapter(project_path=project_path, timeout=timeout, config=config)
    raise ValueError(f"unknown scanner tool: {tool}")


class ScannerRegistry:
    """Хранит набор адаптеров, доступных для текущего проекта."""

    def __init__(self) -> None:
        self._scanners: dict[str, BaseScanner] = {}

    def register(self, scanner: BaseScanner) -> None:
        """Добавляет адаптер. Имя сканера — уникальный ключ (перезапись)."""
        if not scanner.name:
            raise ValueError("scanner.name must be non-empty")
        self._scanners[scanner.name] = scanner

    def get(self, name: str) -> BaseScanner | None:
        return self._scanners.get(name)

    def all(self) -> list[BaseScanner]:
        return list(self._scanners.values())

    def names(self) -> list[str]:
        return list(self._scanners.keys())

    def __contains__(self, name: object) -> bool:
        return name in self._scanners

    def __len__(self) -> int:
        return len(self._scanners)

    def __iter__(self) -> Iterator[BaseScanner]:
        return iter(self._scanners.values())

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        project_path: str | None = None,
        timeout: float | int = 120,
        resolved_rules: ResolvedRules | None = None,
    ) -> ScannerRegistry:
        """Собирает реестр из конфига проекта.

        Для каждой категории (sast/secrets/sca/iac) берётся адаптер её
        инструмента (из `tool` или дефолт категории). Отключённые категории
        пропускаются. Дубликаты (sca + iac → trivy) схлопываются по имени.
        `resolved_rules` прокидываются в адаптеры; если не переданы явно,
        берутся из `config.resolved_rules` (дизайн v1 §3.3).
        """
        registry = cls()
        root = project_path or config.project_path or "."
        rules = resolved_rules if resolved_rules is not None else config.resolved_rules
        for category in _CATEGORY_FIELDS:
            scanner_config: ScannerConfig = getattr(config.scanners, category)
            if not scanner_config.enabled:
                continue
            tool = scanner_config.tool.strip().lower() or _DEFAULT_TOOL_BY_CATEGORY.get(
                category, ""
            )
            if tool not in _TOOL_NAMES:
                continue
            if tool in registry:
                continue
            adapter = _build_adapter(
                tool,
                project_path=root,
                timeout=timeout,
                config=scanner_config,
                resolved_rules=rules,
            )
            registry.register(adapter)
        return registry
