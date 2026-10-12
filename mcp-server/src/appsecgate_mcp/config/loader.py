"""Загрузка конфигурации с приоритетом: env > project config > default."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from appsecgate_mcp.config.models import Config
from appsecgate_mcp.rules import (
    DistributionMode,
    LicenseGuard,
    RuleResolver,
    load_manifest_soft,
)

DEFAULT_CONFIG_PATH = Path("/etc/appsecgate/default.yaml")
PROJECT_CONFIG_REL = ".appsecgate-mcp/config.yaml"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивный merge словарей: override побеждает, dict-значения сливаются."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Переменные окружения перекрывают YAML.

    Простые overrides для Фазы 1:
      APPSECGATE_SCANNERS_SAST_ENABLED=false
      APPSECGATE_GATES_CI_BLOCK_ON_UNRESOLVED_LOCAL=true
    Схема: APPSECGATE_<SECTION>_<SUBSECTION>_<KEY>=value, регистр не важен.
    """
    result = deepcopy(data)
    for env_key, env_value in os.environ.items():
        if not env_key.startswith("APPSECGATE_"):
            continue
        # APPSECGATE_SCANNERS_SAST_ENABLED -> scanners.sast.enabled
        parts = env_key.removeprefix("APPSECGATE_").lower().split("_")
        if len(parts) < 2:
            continue
        node: dict[str, Any] = result
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = _parse_env_value(env_value)
    return result


def _parse_env_value(raw: str) -> Any:
    lowered = raw.strip().lower()
    if lowered in ("true", "yes", "1"):
        return True
    if lowered in ("false", "no", "0"):
        return False
    return raw


def resolve_dirs() -> tuple[Path, Path]:
    """Возвращает (data_dir, cache_dir) с учётом HOME контейнера/машины."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    base = Path(os.environ.get("APPSECGATE_MCP_HOME", str(home / ".appsecgate-mcp")))
    cache = Path(os.environ.get("APPSECGATE_MCP_CACHE_DIR", str(base / "cache")))
    return base, cache


class ConfigLoader:
    """Загружает и кеширует конфигурацию проекта."""

    def __init__(self, default_config_path: Path | None = None) -> None:
        self.default_config_path = default_config_path or DEFAULT_CONFIG_PATH
        self._cache: dict[str, Config] = {}

    def load(self, project_path: str | Path | None = None) -> Config:
        """Загружает конфигурацию для проекта (с кешем по пути)."""
        project = Path(project_path) if project_path else Path.cwd()
        cache_key = str(project.resolve())
        if cache_key in self._cache:
            return self._cache[cache_key]

        data = self._load_default_dict()
        project_data = self._load_project_dict(project)
        merged = deep_merge(data, project_data)
        merged = _apply_env_overrides(merged)

        base_dir, cache_dir = resolve_dirs()
        merged.setdefault("project_path", str(project.resolve()))
        merged.setdefault("cache_dir", str(cache_dir))

        config = Config.model_validate(merged)
        config.project_path = str(project.resolve())
        config.data_dir = str(base_dir)
        config.cache_dir = str(cache_dir)
        self._resolve_rules(config)

        self._cache[cache_key] = config
        return config

    def _resolve_rules(self, config: Config) -> None:
        """Разрешает Rules Bundle и проверяет лицензии (дизайн v1 §3.3, этап 2).

        Fail-soft: любые проблемы попадают в `config.rules_warnings`,
        `resolved_rules` остаётся валидным (возможно пустым) объектом.
        """
        resolver = RuleResolver.from_config(config)
        try:
            resolved = resolver.resolve(
                distribution_mode=config.rules.distribution_mode,
            )
        except Exception as exc:  # noqa: BLE001 - fail-soft контракт
            config.resolved_rules = None
            config.rules_warnings = [f"rules resolution failed: {exc}"]
            return

        warnings = list(resolved.warnings)
        warnings.extend(self._license_warnings(resolver, config.rules.distribution_mode))
        config.resolved_rules = resolved
        config.rules_warnings = warnings

    @staticmethod
    def _license_warnings(resolver: RuleResolver, mode: DistributionMode) -> list[str]:
        """Проверяет лицензионную чистоту дефолтного манифеста (fail-soft)."""
        manifest, warning = load_manifest_soft(resolver.default_root / "manifest.yaml")
        if manifest is None:
            return [warning] if warning else []
        warnings = list(LicenseGuard.warnings(manifest, mode))
        warnings.extend(LicenseGuard.check(manifest, mode))
        return warnings

    def _load_default_dict(self) -> dict[str, Any]:
        if self.default_config_path.exists():
            try:
                return yaml.safe_load(self.default_config_path.read_text()) or {}
            except yaml.YAMLError:
                pass
        return {}

    def _load_project_dict(self, project: Path) -> dict[str, Any]:
        config_file = project / PROJECT_CONFIG_REL
        if config_file.exists():
            try:
                return yaml.safe_load(config_file.read_text()) or {}
            except yaml.YAMLError:
                return {}
        return {}

    def load_config_file(self, path: str | Path) -> Config:
        """Загружает конкретный файл конфига (для get_config/update_config)."""
        file_path = Path(path)
        data = self._load_default_dict()
        if file_path.exists():
            data = deep_merge(data, yaml.safe_load(file_path.read_text()) or {})
        data = _apply_env_overrides(data)
        base_dir, cache_dir = resolve_dirs()
        config = Config.model_validate(data)
        config.data_dir = str(base_dir)
        config.cache_dir = str(cache_dir)
        self._resolve_rules(config)
        return config
