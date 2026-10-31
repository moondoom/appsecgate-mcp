"""Регистрация MCP-тулов.

Порядок импорта модулей = порядок регистрации тулов в FastMCP
(совпадает с порядком в исходном ``server.py``).
"""

from __future__ import annotations

from appsecgate_mcp.server.tools import (  # noqa: F401
    config,
    context,
    feedback,
    gate,
    history,
    query,
    scan,
    verify,
)
