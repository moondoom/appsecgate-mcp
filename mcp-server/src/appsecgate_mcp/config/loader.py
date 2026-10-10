"""Загрузка конфигурации с приоритетом: env > project config > default."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from appsecgate_mcp.config.models import Config

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

        self._cache[cache_key] = config
        return config

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
        return config
