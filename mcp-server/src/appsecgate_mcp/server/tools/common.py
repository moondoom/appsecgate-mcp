"""Общие помощники для модулей MCP-тулов."""

from __future__ import annotations

import appsecgate_mcp.server as server_mod
from appsecgate_mcp.server.session import SessionState

# Лимит батч-тулов (get_fix_context_batch / verify_fix_batch).
_BATCH_LIMIT = 20


async def ensure_session(project_path: str | None = None) -> SessionState:
    """Лениво инициализирует сессию (уважает monkeypatch ``server._ensure_session``).

    Атрибут пакета читается в момент вызова, поэтому подмена в тестах
    (``monkeypatch.setattr(server, "_ensure_session", ...)``) видна тулам.
    """
    return await server_mod._ensure_session(project_path)
