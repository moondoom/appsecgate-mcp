"""MCP-клиент поверх Docker stdio: docker run + mcp ClientSession."""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from subprocess import run as subprocess_run
from typing import Any

logger = logging.getLogger("e2e_measure")


def _parse_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "content") and result.content:
        for part in result.content:
            if hasattr(part, "text") and part.text:
                try:
                    return json.loads(part.text)
                except json.JSONDecodeError:
                    return {"raw_text": part.text}
        return {"raw": str(result.content)}
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    return {"raw": str(result)}


def _find_first_finding_id(results: list[dict[str, Any] | None]) -> str | None:
    for r in results:
        if r is None:
            continue
        # scan_file возвращает announce-формат: детали в top_findings.
        for key in ("top_findings", "findings"):
            for item in r.get(key, []):
                fid = item.get("finding_id") or item.get("fingerprint")
                if fid:
                    return fid
    return None


def _counts_total(payload: dict[str, Any]) -> int:
    """Итог отчёта scan_project (ADR-0005 §2.5) — сумма по категориям ``counts``."""
    return sum(int(v) for v in payload.get("counts", {}).values())


def _docker_args(
    project_path: str,
    image: str = "moondoom/appsecgate-mcp:0.1.0",
    cache_volume: str = "appsecgate-cache",
    data_volume: str = "appsecgate-data",
    mount_path: str = "/workspace",
    *,
    read_only: bool = True,
    memory_limit: str | None = None,
    name: str | None = None,
) -> list[str]:
    """Билд docker run для stdio-сессии.

    ``mount_path`` — путь внутри контейнера, куда монтируется проект.
    Для параллельных сессий используется разный ``mount_path``: project_id
    вычисляется как sha256(realpath(project_path)), поэтому при одинаковом
    пути оба проекта получили бы один project_id.

    ``read_only=False`` — rw-монтаж проекта + снятие ``--read-only``: только для
    E2E-сценариев «фикс» (verify_fix=fixed) на временной копии полигона.
    ``memory_limit`` — ``--memory`` контейнера (E1: проверка риска OOM).
    ``name`` — имя контейнера (для ``docker stats`` в E1).
    """
    resolved = str(Path(project_path).resolve())
    mount = f"{resolved}:{mount_path}:{'ro' if read_only else 'rw'}"
    args = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network=none",
        "--tmpfs=/tmp:size=100M,mode=1777",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--user=1000:1000",
    ]
    if read_only:
        args.append("--read-only")
    if memory_limit:
        args += ["--memory", memory_limit]
    if name:
        args += ["--name", name]
    args += [
        "-v",
        mount,
        "-v",
        f"{resolved}/.appsecgate-mcp:/.appsecgate-mcp:ro",
        "-v",
        f"{cache_volume}:/home/appsecgate/.cache",
        "-v",
        f"{data_volume}:/home/appsecgate/.appsecgate-mcp",
        "-e",
        f"APPSECGATE_PROJECT_PATH={mount_path}",
        "-e",
        "HOME=/home/appsecgate",
        image,
        "--transport",
        "stdio",
    ]
    return args


class McpClient:
    def __init__(
        self,
        project_path: str,
        mount_path: str = "/workspace",
        data_volume: str = "appsecgate-data",
        *,
        read_only: bool = True,
        memory_limit: str | None = None,
        name: str | None = None,
    ) -> None:
        self.project_path = project_path
        self.mount_path = mount_path
        self.data_volume = data_volume
        self.read_only = read_only
        self.memory_limit = memory_limit
        self.name = name
        self._stack = AsyncExitStack()
        self._session: Any = None

    async def __aenter__(self) -> McpClient:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        cmd = _docker_args(
            self.project_path,
            mount_path=self.mount_path,
            data_volume=self.data_volume,
            read_only=self.read_only,
            memory_limit=self.memory_limit,
            name=self.name,
        )
        sp = StdioServerParameters(command=cmd[0], args=cmd[1:])
        self._read, self._write = await self._stack.enter_async_context(stdio_client(sp))
        self._session = await self._stack.enter_async_context(
            ClientSession(self._read, self._write)
        )
        await self._session.initialize()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._stack.aclose()

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return await self._session.call_tool(name, arguments or {})
