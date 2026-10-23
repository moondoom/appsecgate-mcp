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


def _readme_tool_names() -> set[str]:
    text = README.read_text(encoding="utf-8")
    header_match = re.search(r"## MCP tools \((\d+)\)", text)
    assert header_match, "в README нет заголовка «## MCP tools (14)»"
    section_start = header_match.end()
    next_header = re.search(r"\n## ", text[section_start:])
    section_text = (
        text[section_start : section_start + next_header.start()]
        if next_header
        else text[section_start:]
    )
    return set(re.findall(r"`([a-z_]+)`", section_text))


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
