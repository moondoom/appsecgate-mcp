"""Сверка документации с реальным состоянием MCP-сервера.

Список инструментов в README должен совпадать с mcp.list_tools(). Расхождение
валит тест, а значит и make check.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from appsecgate_mcp.server import mcp

README = Path(__file__).resolve().parents[2] / "README.md"
_TOOLS_LINE = re.compile(r"MCP-инструменты \(\d+\):\*\*(.+)")


def _readme_tool_names() -> set[str]:
    text = README.read_text(encoding="utf-8")
    match = _TOOLS_LINE.search(text)
    assert match, "в README нет строки «MCP-инструменты (N):»"
    return set(re.findall(r"`([a-z_]+)`", match.group(1)))


def _registered_tool_names() -> set[str]:
    tools = asyncio.run(mcp.list_tools())
    return {tool.name for tool in tools}


def test_readme_tools_match_list_tools() -> None:
    assert _readme_tool_names() == _registered_tool_names()


def test_exactly_fourteen_tools() -> None:
    assert len(_registered_tool_names()) == 14


def test_hooks_are_not_mcp_tools() -> None:
    registered = _registered_tool_names()
    assert not {"session_start", "pre_tool_use", "post_tool_use"} & registered
