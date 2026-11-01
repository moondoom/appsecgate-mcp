"""CLI-контракт report mode."""

from __future__ import annotations

from appsecgate_agent.cli import main
from appsecgate_agent.mcp_client import McpClient


def test_missing_mcp_command_is_infrastructure_error(capsys):
    assert main([]) == 2
    assert "--mcp-command is required" in capsys.readouterr().err


def test_empty_mcp_command_is_rejected():
    try:
        McpClient("")
    except ValueError as exc:
        assert str(exc) == "MCP command is empty"
    else:
        raise AssertionError("empty command must fail")
