"""Pydantic-модели конфигурации SecGate MCP."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StackConfig(BaseModel):
    """Определение стека проекта."""

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)


class ScannerConfig(BaseModel):
    """Настройки отдельного сканера."""

    enabled: bool = True
    tool: str = ""
    rulesets: list[str] = Field(default_factory=list)
    severity_threshold: str = "medium"
    extra_options: dict[str, Any] = Field(default_factory=dict)


class ScannersConfig(BaseModel):
    """Корневой блок scanners в config.yaml."""

    sast: ScannerConfig = Field(default_factory=ScannerConfig)
    secrets: ScannerConfig = Field(default_factory=ScannerConfig)
    sca: ScannerConfig = Field(default_factory=ScannerConfig)
    iac: ScannerConfig = Field(default_factory=ScannerConfig)


class GateRuleConfig(BaseModel):
    """Правила gate: при каких severity что делать."""

    block_on: list[str] = Field(default_factory=list)
    warn_on: list[str] = Field(default_factory=list)
    info_on: list[str] = Field(default_factory=list)


class LocalGateConfig(GateRuleConfig):
    """Локальный gate — по умолчанию ничего не блокируем."""

    warn_on: list[str] = Field(default_factory=lambda: ["critical", "high", "medium"])
    block_on: list[str] = Field(default_factory=list)


class CiGateConfig(GateRuleConfig):
    """CI-gate — блокируем critical/high (используется для валидации конфига)."""

    block_on: list[str] = Field(default_factory=lambda: ["critical", "high"])
    warn_on: list[str] = Field(default_factory=lambda: ["medium"])
    block_on_unresolved_local: bool = True


class GatesConfig(BaseModel):
    """Двойной контур gates."""

    local: LocalGateConfig = Field(default_factory=LocalGateConfig)
    ci: CiGateConfig = Field(default_factory=CiGateConfig)


class AutoFixConfig(BaseModel):
    """Настройки автофикса (уровень 0 воронки эскалации)."""

    enabled: bool = True
    strategies: list[str] = Field(default_factory=lambda: ["patch", "suggestion"])
    max_attempts: int = 1


class SuppressRuleConfig(BaseModel):
    """Одно правило подавления из config.yaml."""

    rule: str = ""
    paths: list[str] = Field(default_factory=list)
    reason: str = ""
    scope: str = "local"


class SLAConfig(BaseModel):
    """Таймеры эскалации (не используются в Фазе 1, но валидируются)."""

    dev_response: str = "24h"
    dev_after_block: str = "48h"
    appsec_response: str = "5d"
    lead_response: str = "10d"


class Config(BaseModel):
    """Корневая модель конфигурации."""

    version: int = 2
    stack: StackConfig = Field(default_factory=StackConfig)
    scanners: ScannersConfig = Field(default_factory=ScannersConfig)
    gates: GatesConfig = Field(default_factory=GatesConfig)
    auto_fix: AutoFixConfig = Field(default_factory=AutoFixConfig)
    suppress: list[SuppressRuleConfig] = Field(default_factory=list)
    sla: SLAConfig = Field(default_factory=SLAConfig)

    # Не из YAML, заполняется загрузчиком
    project_path: str | None = None
    cache_dir: str = ""
    data_dir: str = ""

    def severity_threshold_value(self, category: str) -> str:
        """Возвращает порог severity для категории сканера."""
        scanner = getattr(self.scanners, category)
        return (scanner.severity_threshold or "medium").lower()

    def enabled_scanner_categories(self) -> list[str]:
        """Категории сканеров, включённые в конфиге."""
        result = []
        for category in ("sast", "secrets", "sca", "iac"):
            scanner = getattr(self.scanners, category)
            if scanner.enabled:
                result.append(category)
        return result


def _default_config() -> Config:
    """Встроенная конфигурация по умолчанию (fallback, если файла нет)."""
    return Config()
