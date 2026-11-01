"""Runner server-agent: последовательность вызовов и ошибки скана."""

from __future__ import annotations

import pytest

from appsecgate_agent.runner import run_report


class FakeClient:
    def __init__(self, scan: dict | None = None) -> None:
        self.scan = scan or {"summary": {"total": 1}}
        self.calls: list[tuple[str, dict | None]] = []

    async def call(self, tool: str, arguments: dict | None = None) -> dict:
        self.calls.append((tool, arguments))
        if tool.startswith("scan_"):
            return self.scan
        return {"should_fail": False, "recommended_action": "proceed"}


async def test_diff_report_calls_scan_then_gate():
    client = FakeClient()

    result = await run_report(client, scope="diff", policy="block")

    assert client.calls == [
        ("scan_diff", None),
        ("check_gate", {"scope": "diff", "policy": "block"}),
    ]
    assert result.gate["recommended_action"] == "proceed"


async def test_full_report_uses_scan_project():
    client = FakeClient()

    await run_report(client, scope="full", policy="escalate")

    assert client.calls == [
        ("scan_project", None),
        ("check_gate", {"scope": "full", "policy": "escalate"}),
    ]


async def test_scan_error_stops_before_gate():
    client = FakeClient({"error": "git failed"})

    with pytest.raises(RuntimeError, match="scan_diff failed: git failed"):
        await run_report(client, scope="diff", policy="block")

    assert client.calls == [("scan_diff", None)]
