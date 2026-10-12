"""Базовые модели находок и результатов сканирования.

Единый формат `Finding`, в который нормализуются выводы всех сканеров
(Semgrep, Gitleaks, TruffleHog, Trivy), плюс вспомогательные структуры:
результаты скана, автофикса и локальных suppression.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class Severity(StrEnum):
    """Уровень критичности находки.

    Используется и сортировкой, и GateEngine (локальный warn / CI block).
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# Чем выше число, тем «серьёзнее». Используется при сортировке результатов.
SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 5,
    Severity.HIGH: 4,
    Severity.MEDIUM: 3,
    Severity.LOW: 2,
    Severity.INFO: 1,
}


class Category(StrEnum):
    """Категория находки — отображает тип сканера, который её создал."""

    SAST = "sast"
    SECRET = "secret"
    SCA = "sca"
    IAC = "iac"
    LICENSE = "license"


class Finding(BaseModel):
    """Нормализованная находка — единый формат для всех сканеров."""

    fingerprint: str = ""  # Детерминированный ID (см. FingerprintGenerator)
    rule_id: str
    severity: Severity
    file_path: str  # относительный путь к файлу
    line_start: int = 1
    line_end: int = 1
    message: str = ""
    scanner: str  # semgrep | gitleaks | trufflehog | trivy
    category: Category
    snippet: str = ""  # нормализуемый для fingerprint фрагмент кода
    metadata: dict[str, Any] = Field(default_factory=dict)
    remediation: str | None = None

    def with_fingerprint(self, fingerprint: str) -> Finding:
        """Возвращает self с проставленным fingerprint (fluent API)."""
        self.fingerprint = fingerprint
        return self

    def sort_key(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 0)

    def display_id(self) -> str:
        """Короткий идентификатор для показа разработчику."""
        return self.fingerprint or f"{self.scanner}:{self.rule_id}:{self.file_path}"

    def has_known_patch(self) -> bool:
        """Есть ли готовый патч (метаданные от сканера или правила)."""
        return bool(self.metadata.get("patch"))

    def generate_patch(self) -> str | None:
        """Возвращает готовый патч, если он есть."""
        return self.metadata.get("patch")


class ScannerError(BaseModel):
    """Информация о сканере, который не смог отработать."""

    scanner: str
    error: str


class ScanMeta(BaseModel):
    """Метаданные скана: что отработало, что пропущено, предупреждения."""

    mode: str = "file"  # file | diff | project
    duration_ms: float = 0.0
    scanned_files: list[str] = Field(default_factory=list)
    scanners_ran: list[str] = Field(default_factory=list)
    scanners_skipped: list[str] = Field(default_factory=list)
    errors: list[ScannerError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # Инвентаризационный хэш набора правил (дизайн v1 §1.5); None — правила не разрешены.
    ruleset_hash: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class ScanResult(BaseModel):
    """Результат сканирования, возвращаемый MCP-инструментам."""

    findings: list[Finding] = Field(default_factory=list)
    meta: ScanMeta = Field(default_factory=ScanMeta)

    @property
    def total(self) -> int:
        return len(self.findings)

    def to_summary(self) -> dict[str, Any]:
        """Компактная сводка для сериализации в MCP-ответ."""
        by_severity: dict[str, int] = {}
        for f in self.findings:
            key = f.severity.value
            by_severity[key] = by_severity.get(key, 0) + 1
        return {
            "total": self.total,
            "by_severity": by_severity,
            "scanners_ran": self.meta.scanners_ran,
            "scanners_skipped": self.meta.scanners_skipped,
            "warnings": self.meta.warnings,
            "duration_ms": self.meta.duration_ms,
        }


class FixResult(BaseModel):
    """Результат попытки автофикса находки."""

    finding_id: str
    status: str  # patched | suggested | failed | skipped
    patch: str | None = None
    reason: str | None = None


class Suppression(BaseModel):
    """Локальное подавление находки.

    Локальный suppression НЕ подавляет CI-находку (двойной контур gates):
    он только скрывает находку в локальном контуре.
    """

    fingerprint: str
    reason: str
    scope: str = "local"  # local | ci | global (Фаза 1 — только local)
    expires_at: str | None = None
    created_at: str = Field(default_factory=_utcnow_iso)

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        expires = datetime.fromisoformat(self.expires_at)
        return expires < datetime.now(UTC)
