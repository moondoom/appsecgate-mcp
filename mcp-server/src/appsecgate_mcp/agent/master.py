from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class MasterClient:
    def __init__(self, url: str, api_key: str) -> None:
        self.url = f"{url.rstrip('/')}/mcp/"
        self.api_key = api_key
        self.stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None

    async def __aenter__(self) -> MasterClient:
        self.stack = AsyncExitStack()
        try:
            http = await self.stack.enter_async_context(
                httpx.AsyncClient(headers={"Authorization": f"Bearer {self.api_key}"}, timeout=30)
            )
            read, write, _ = await self.stack.enter_async_context(
                streamable_http_client(self.url, http_client=http)
            )
            self.session = await self.stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()
            return self
        except BaseException:
            await self.stack.aclose()
            raise

    async def __aexit__(self, *args: Any) -> None:
        if self.stack is not None:
            await self.stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("master MCP session is not initialized")
        result = await self.session.call_tool(name, arguments)
        if result.isError:
            text = "".join(getattr(item, "text", "") for item in result.content)
            raise RuntimeError(f"master MCP tool failed: {text}")
        if result.structuredContent is not None:
            return dict(result.structuredContent)
        text = "".join(getattr(item, "text", "") for item in result.content)
        value = json.loads(text)
        if not isinstance(value, dict):
            raise RuntimeError("master MCP tool returned a non-object result")
        return value
