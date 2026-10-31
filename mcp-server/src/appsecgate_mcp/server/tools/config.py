"""Тулы конфигурации: get_config, update_config (+ атомарная запись)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from appsecgate_mcp.config.loader import PROJECT_CONFIG_REL, ConfigLoader, deep_merge
from appsecgate_mcp.config.models import Config
from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.session import SessionState
from appsecgate_mcp.server.tools.common import ensure_session

# Шов для тестов: подменяется точечно (monkeypatch server._replace_file),
# не трогая os.replace глобально.
_replace_file = os.replace

# Шов для тестов: проверка доступности записи в проект (T11).
_os_access = os.access


def _atomic_write(path: Path, text: str) -> None:
    """Атомарная запись: временный файл в той же директории, затем os.replace."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        import appsecgate_mcp.server as server_mod

        server_mod._replace_file(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _format_validation_errors(exc: ValidationError) -> list[str]:
    """Превращает ошибки pydantic в строки вида 'путь.к.полю: сообщение'."""
    messages: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        messages.append(f"{loc}: {err['msg']}")
    return messages


def _is_project_writable(project_path: str) -> bool:
    """Проверяет доступность записи в корень проекта без реальной записи.

    В каноническом Docker-деплое проект смонтирован ``:ro`` — ``os.access``
    вернёт False, и ``update_config`` вернёт рекомендацию вместо падения (T11).
    """
    try:
        return _os_access(project_path, os.W_OK)
    except OSError:
        return False


def _restore_config(path: Path, previous_text: str | None) -> None:
    """Возвращает файл конфига к предыдущему содержимому (или удаляет, если его не было)."""
    if previous_text is None:
        path.unlink(missing_ok=True)
    else:
        _atomic_write(path, previous_text)


async def _reinitialize(state: SessionState) -> None:
    """Пересоздаёт ConfigLoader и переинициализирует сессию под текущий проект."""
    state.config_loader = ConfigLoader(state.config_loader.default_config_path)
    await state.initialize(state.project_path, force=True)


@mcp.tool()
@_log_tool
async def get_config() -> dict[str, Any]:
    """Return the active (merged) session configuration."""
    state = await ensure_session()
    return state.config.model_dump(mode="json")


@mcp.tool()
@_log_tool
async def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge updates into .appsecgate-mcp/config.yaml and reload the session.

    The resulting config is validated against the same schema as ConfigLoader.load
    before writing. Invalid results return status=invalid, file unchanged.
    """
    state = await ensure_session()
    project_conf = Path(state.project_path) / PROJECT_CONFIG_REL

    if not _is_project_writable(state.project_path):
        # Канонический деплой монтирует проект :ro — это НЕ ошибка сервера
        # и не проблема окружения: так задумано (инвариант №1). Отдаём понятный
        # агенту статус readonly с рекомендацией спросить пользователя (T11).
        return {
            "status": "readonly",
            "applied": False,
            "config_path": str(project_conf),
            "reason": (
                "project is mounted read-only; the server cannot write "
                ".appsecgate-mcp/config.yaml (project files are never written). "
                "This is expected in the canonical Docker deployment, not an error."
            ),
            "how_to_change": (
                "The change was NOT applied. To adjust settings, ask the user to "
                "edit .appsecgate-mcp/config.yaml in the host project, mount the "
                "project read-write for local (Docker-free) use, or set APPSECGATE_* "
                "env variables."
            ),
        }

    existing: dict[str, Any] = {}
    previous_text: str | None = None
    if project_conf.exists():
        previous_text = project_conf.read_text(encoding="utf-8")
        try:
            existing = yaml.safe_load(previous_text) or {}
        except yaml.YAMLError:
            existing = {}
    merged = deep_merge(existing, updates)

    try:
        Config.model_validate(
            state.config_loader.validation_layers(
                merged,
                data_dir=state.config.data_dir,
                project_id=state.project_id,
            )
        )
    except ValidationError as exc:
        return {"status": "invalid", "errors": _format_validation_errors(exc)}

    project_conf.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(project_conf, yaml.safe_dump(merged, allow_unicode=True, sort_keys=False))

    try:
        await _reinitialize(state)
    except Exception as exc:
        _restore_config(project_conf, previous_text)
        try:
            await _reinitialize(state)
        except Exception:
            pass
        return {
            "status": "error",
            "reason": f"reinitialization failed, config rolled back: {exc}",
            "config_path": str(project_conf),
        }
    return {
        "status": "updated",
        "config_path": str(project_conf),
        "config": state.config.model_dump(mode="json"),
    }
