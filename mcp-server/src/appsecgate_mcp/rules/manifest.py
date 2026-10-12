"""Модели и загрузчик `manifest.yaml` — индекса Rules Bundle.

Манифест описывает наборы правил (bundles) с лицензионными метаданными
и, опционально, overlay-настройки (disable/replace). См. дизайн v1 §1.4.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class DistributionMode(StrEnum):
    """Режим поставки сборки.

    `mit` — публичная сборка (разрешены только permissive/weak-copyleft);
    `commercial` — коммерческая (позволяет restricted-бандлы, напр. Commons Clause).
    """

    MIT = "mit"
    COMMERCIAL = "commercial"


class Redistribution(StrEnum):
    """Разрешение на распространение бандла."""

    ALLOWED = "allowed"
    RESTRICTED = "restricted"
    INTERNAL = "internal"


class BundleEntry(BaseModel):
    """Один набор правил из манифеста."""

    id: str
    scanner: str
    path: str
    license: str = ""
    source: str = ""
    redistribution: Redistribution = Redistribution.ALLOWED
    min_scanner_version: str | None = None
    tags: list[str] = Field(default_factory=list)


class ScannerOverrides(BaseModel):
    """Overlay-настройки для конкретного сканера (без deep-merge).

    `disable` — ID правил, которые надо выключить;
    `replace` — карта `rule-id -> путь к файлу-замене`.
    """

    disable: list[str] = Field(default_factory=list)
    replace: dict[str, str] = Field(default_factory=dict)


class Overrides(BaseModel):
    """Корневой блок `overrides` overlay-манифеста."""

    semgrep: ScannerOverrides = Field(default_factory=ScannerOverrides)
    gitleaks: ScannerOverrides = Field(default_factory=ScannerOverrides)
    trufflehog: ScannerOverrides = Field(default_factory=ScannerOverrides)
    trivy: ScannerOverrides = Field(default_factory=ScannerOverrides)

    def for_scanner(self, scanner: str) -> ScannerOverrides:
        """Возвращает override-блок сканера по имени (или пустой)."""
        value = getattr(self, scanner.lower(), None)
        return value if isinstance(value, ScannerOverrides) else ScannerOverrides()


class RulesManifest(BaseModel):
    """Корневая модель `manifest.yaml`."""

    version: str = "0.0.0"
    distribution_mode: DistributionMode = DistributionMode.MIT
    bundles: list[BundleEntry] = Field(default_factory=list)
    overrides: Overrides | None = None


class ManifestError(RuntimeError):
    """Ошибка загрузки/валидации манифеста."""


def load_manifest(path: str | Path) -> RulesManifest:
    """Загружает и валидирует `manifest.yaml`.

    Fail-soft вызывающая сторона обеспечивает сама: эта функция честно
    поднимает `ManifestError`, чтобы решение об откате принимал резолвер.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise ManifestError(f"manifest not found: {file_path}")
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ManifestError(f"invalid yaml in {file_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"manifest root must be a mapping: {file_path}")
    try:
        return RulesManifest.model_validate(data)
    except Exception as exc:  # pydantic ValidationError и др.
        raise ManifestError(f"invalid manifest schema in {file_path}: {exc}") from exc


def load_manifest_soft(path: str | Path) -> tuple[RulesManifest | None, str | None]:
    """Мягкая загрузка: возвращает `(manifest, warning)` без исключений."""
    try:
        return load_manifest(path), None
    except ManifestError as exc:
        return None, str(exc)
