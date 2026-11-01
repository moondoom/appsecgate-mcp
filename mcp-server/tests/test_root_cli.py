from __future__ import annotations

import pytest

from appsecgate_mcp import cli


@pytest.mark.parametrize(
    ("command", "module", "function"),
    [
        ("serve", "appsecgate_mcp.server.cli", "serve_main"),
        ("sync", "appsecgate_mcp.sync.cli", "sync_main"),
        ("ci", "appsecgate_mcp.server.ci", "ci_main"),
        ("hook", "appsecgate_mcp.hooks", "hook_main"),
        ("agent", "appsecgate_mcp.agent.cli", "agent_main"),
    ],
)
def test_dispatches_subcommand(monkeypatch, command, module, function):
    calls = []
    monkeypatch.setattr(f"{module}.{function}", lambda argv: calls.append(argv))

    with pytest.raises(SystemExit) as exc:
        cli.main([command, "--flag"])

    assert exc.value.code is None
    assert calls == [["--flag"]]


def test_legacy_arguments_keep_serve_entrypoint(monkeypatch):
    calls = []
    monkeypatch.setattr("appsecgate_mcp.server.main", lambda: calls.append([]))

    cli.main(["--transport", "stdio"])

    assert calls == [[]]
