"""Smoke-тесты MCP Server Layer: регистрация инструментов, хуков и CLI."""

from __future__ import annotations

import asyncio

import pytest

from appsecgate_mcp import server


def test_all_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    expected = {
        "scan_file",
        "scan_diff",
        "scan_project",
        "auto_fix",
        "get_config",
        "update_config",
        "submit_feedback",
        "get_scan_history",
        "suppress_finding",
        "session_start",
        "pre_tool_use",
        "post_tool_use",
    }
    assert expected.issubset(names)


def test_extract_touched_files():
    files = server._extract_touched_files("Edit", {"file_path": "/abs/a.py"})
    assert files
    assert server._extract_touched_files("Read", {"file_path": "a.py"}) == []
    assert server._extract_touched_files("Write", {}) == []


def test_parser_accepts_streamable_http():
    parser = server._build_parser()
    args = parser.parse_args(["--transport", "streamable-http", "--port", "9000"])
    assert args.transport == "streamable-http"
    assert args.port == 9000


def test_parser_default_transport_is_stdio():
    parser = server._build_parser()
    assert parser.parse_args([]).transport == "stdio"


def test_parser_rejects_unknown_transport():
    parser = server._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--transport", "websocket"])


def test_sse_transport_emits_deprecation_warning(monkeypatch):
    # Не поднимаем реальный сервер — перехватываем mcp.run.
    captured: dict[str, str] = {}

    def fake_run(*, transport: str) -> None:
        captured["transport"] = transport

    monkeypatch.setattr(server.mcp, "run", fake_run)
    monkeypatch.setattr(server, "_configure_http", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", ["appsecgate-mcp", "--transport", "sse"])

    with pytest.warns(DeprecationWarning):
        server.main()
    assert captured["transport"] == "sse"


def test_streamable_http_configures_host_port(monkeypatch):
    captured: dict[str, str] = {}

    def fake_run(*, transport: str) -> None:
        captured["transport"] = transport

    configured: dict[str, int | str] = {}

    def fake_configure(host: str, port: int) -> None:
        configured["host"] = host
        configured["port"] = port

    monkeypatch.setattr(server.mcp, "run", fake_run)
    monkeypatch.setattr(server, "_configure_http", fake_configure)
    monkeypatch.setattr(
        "sys.argv",
        ["appsecgate-mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8123"],
    )

    server.main()
    assert captured["transport"] == "streamable-http"
    assert configured == {"host": "0.0.0.0", "port": 8123}
