"""Normalizer — маппинг severity и пост-обработка нормализованных находок."""

from __future__ import annotations

from appsecgate_mcp.config.models import Config
from appsecgate_mcp.models.finding import SEVERITY_ORDER, Category, Finding, Severity

# Приём собственных severity-строк сканеров к нашей шкале.
# Ключ — lowercase-строка от сканера, значение — наше Severity.
_SEVERITY_MAP: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "error": Severity.HIGH,
    "fatal": Severity.CRITICAL,
    "medium": Severity.MEDIUM,
    "moderate": Severity.MEDIUM,
    "low": Severity.LOW,
    "info": Severity.INFO,
    "warning": Severity.LOW,
    "note": Severity.INFO,
    "unknown": Severity.INFO,
}

# Маппинг категории находки на ключ ScannerConfig в ScannersConfig.
# Используется для выбора severity_threshold из конфигурации.
_CATEGORY_CONFIG_KEY: dict[Category, str] = {
    Category.SAST: "sast",
    Category.SECRET: "secrets",
    Category.SCA: "sca",
    Category.IAC: "iac",
    Category.LICENSE: "sca",
}


def normalize_severity(raw_severity: str) -> Severity:
    """Маппит строку severity сканера в наше перечисление.

    Неизвестные значения понижаются до INFO — шум не должен пугать.
    """
    return _SEVERITY_MAP.get((raw_severity or "").strip().lower(), Severity.INFO)


class Normalizer:
    """Применяет severity-маппинг, пороги, fingerprint и фильтрацию."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def normalize_severity(self, raw_severity: str) -> Severity:
        """Прокси на module-level функцию (для удобства вызова и тестирования)."""
        return normalize_severity(raw_severity)

    def _severity_rank(self, severity: Severity) -> int:
        """Числовой ранг severity для сравнения с порогом (выше — серьёзнее)."""
        return SEVERITY_ORDER.get(severity, 0)

    def filter_by_threshold(
        self, findings: list[Finding], category: Category
    ) -> list[Finding]:
        """Оставляет находки не ниже severity_threshold для своей категории.

        Порог берётся из config.scanners.<category>.severity_threshold
        (для LICENSE используется порог категории SCA).
        """
        config_key = _CATEGORY_CONFIG_KEY.get(category, "sast")
        threshold_raw = self.config.severity_threshold_value(config_key)
        threshold = normalize_severity(threshold_raw)
        min_rank = self._severity_rank(threshold)
        return [f for f in findings if self._severity_rank(f.severity) >= min_rank]

    def process(self, findings: list[Finding]) -> list[Finding]:
        """Полный пайплайн нормализации в зоне ответственности этого класса.

        Шаги:
          1. Фильтрация по severity_threshold категории сканера.
          2. Сортировка по убыванию severity.

        Fingerprint и дедупликация НЕ выполняются здесь — это зона ответственности
        FingerprintGenerator и Deduplicator (см. ScanCoordinator, architecture.md §3.2).
        Исходные severity уже приведены к `Severity` адаптерами через
        module-level `normalize_severity` до создания `Finding`.
        """
        grouped: dict[Category, list[Finding]] = {}
        for f in findings:
            grouped.setdefault(f.category, []).append(f)

        filtered: list[Finding] = []
        for category, items in grouped.items():
            filtered.extend(self.filter_by_threshold(items, category))

        return sorted(filtered, key=lambda f: self._severity_rank(f.severity), reverse=True)
