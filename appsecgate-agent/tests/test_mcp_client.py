"""Интеграционная проверка stdio-протокола с настоящим MCP-сервером."""

from __future__ import annotations

from pathlib import Path

from appsecgate_agent.mcp_client import McpClient


async def test_check_gate_over_real_stdio(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPSECGATE_DATA_DIR", str(tmp_path / "data"))
    client = McpClient(
        f"uv run --directory {root / 'mcp-server'} appsecgate-mcp "
        f"--transport stdio --project {tmp_path}"
    )

    result = await client.call("check_gate", {"scope": "diff", "policy": "block"})

    assert result["should_fail"] is False
    assert result["recommended_action"] == "proceed"
    assert result["meta"]["source"] == "local"
