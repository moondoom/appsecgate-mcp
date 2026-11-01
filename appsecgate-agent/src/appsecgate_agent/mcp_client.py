"""Минимальный MCP stdio-клиент для server-agent."""

from __future__ import annotations

import json
import shlex
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpClient:
    def __init__(self, command: str) -> None:
        parts = shlex.split(command)
        if not parts:
            raise ValueError("MCP command is empty")
        self._params = StdioServerParameters(command=parts[0], args=parts[1:])

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async with stdio_client(self._params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments or {})
        if result.isError:
            raise RuntimeError(f"MCP tool {tool} failed: {_text_content(result.content)}")
        if result.structuredContent is not None:
            return dict(result.structuredContent)
        text = _text_content(result.content)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MCP tool {tool} returned no structured result") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"MCP tool {tool} returned a non-object result")
        return payload


def _text_content(content: list[Any]) -> str:
    return "\n".join(item.text for item in content if hasattr(item, "text"))
