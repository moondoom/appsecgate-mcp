"""Базовый интерфейс адаптеров сканеров.

Адаптеры (Semgrep, Gitleaks, TruffleHog, Trivy) предоставляют единый
контракт через `RawFinding` и `BaseScanner`. Сам запуск внешних бинарников
вынесен в `scanners.runner` (без shell, с таймаутом).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from secgate_mcp.models.finding import Category, Finding
from secgate_mcp.normalization.normalizer import normalize_severity
from secgate_mcp.scanners.runner import CommandResult, run_subprocess


@dataclass
class RawFinding:
    """Сырой результат сканера до нормализации в `Finding`.

    Адаптеры обязаны возвращать этот контракт; нормализацией и fingerprinting
    занимается слой нормализации/координатор.
    """

    rule_id: str
    raw_severity: str
    file_path: str
    scanner: str
    line_start: int = 1
    line_end: int = 1
    message: str = ""
    snippet: str = ""
    category: Category = Category.SAST
    metadata: dict[str, Any] = field(default_factory=dict)
    remediation: str | None = None

    def to_finding(self, *, fingerprint: str = "") -> Finding:
        """Конвертирует `RawFinding` в нормализованный `Finding`.

        `raw_severity` маппится через `normalize_severity`, fingerprint может
        быть передан извне (если координатор ещё не успел его вычислить).
        """
        return Finding(
            fingerprint=fingerprint,
            rule_id=self.rule_id,
            severity=normalize_severity(self.raw_severity),
            file_path=self.file_path,
            line_start=self.line_start,
            line_end=self.line_end,
            message=self.message,
            scanner=self.scanner,
            category=self.category,
            snippet=self.snippet,
            metadata=self.metadata,
            remediation=self.remediation,
        )


class BaseScanner(ABC):
    """Базовый интерфейс адаптера сканера.

    Адаптер обязан реализовать `scan` и `is_available`. Метод `run` — общая
    обёртка над subprocess-раннером для запуска бинарника с текущим таймаутом
    и project_path.
    """

    name: str = ""
    supported_languages: frozenset[str] = frozenset()

    def __init__(self, *, project_path: str | None = None, timeout: float | int = 120) -> None:
        self.project_path = project_path or "."
        self.timeout = timeout

    @abstractmethod
    async def scan(self, files: list[str], mode: str) -> list[RawFinding]:
        """Сканирует указанные файлы в режиме `file` | `diff` | `project`.

        Адаптер сам решает, какие из переданных файлов релевантны его типу
        (например, Trivy — только lock-файлы, IaC-манифесты и Dockerfile).
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Проверяет, доступен ли бинарник сканера (PATH и версия)."""

    def scan_source(self, files: list[str], mode: str) -> str:
        """Возвращает директорию-источник для сканеров, гуляющих по ФС.

        В режиме `project` координатор передаёт один путь-директорию (весь
        проект или конкретную папку). Сканеры, работающие по директории
        целиком (gitleaks, trufflehog, trivy), должны сканировать именно её,
        а не безусловно весь `project_path`. В остальных режимах источник —
        корень проекта (результат затем фильтруется по списку файлов).
        """
        if mode == "project" and files:
            target = Path(files[0])
            if not target.is_absolute():
                target = Path(self.project_path) / target
            return str(target)
        return self.project_path or "."

    async def run(
        self, cmd: list[str], *, timeout: float | int | None = None
    ) -> CommandResult:
        """Запускает внешнюю команду адаптера с настроенным таймаутом."""
        return await run_subprocess(
            cmd,
            timeout=self.timeout if timeout is None else timeout,
            cwd=self.project_path,
        )
