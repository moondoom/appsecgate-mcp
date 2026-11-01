"""Детерминированный runner: scan → check_gate → report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

Scope = Literal["diff", "full"]
Policy = Literal["warn", "block", "escalate"]


class Client(Protocol):
    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]: ...


@dataclass(slots=True)
class AgentResult:
    scan: dict[str, Any]
    gate: dict[str, Any]


async def run_report(client: Client, *, scope: Scope, policy: Policy) -> AgentResult:
    scan_tool = "scan_project" if scope == "full" else "scan_diff"
    scan = await client.call(scan_tool)
    if "error" in scan:
        raise RuntimeError(f"{scan_tool} failed: {scan['error']}")
    gate = await client.call("check_gate", {"scope": scope, "policy": policy})
    return AgentResult(scan=scan, gate=gate)
