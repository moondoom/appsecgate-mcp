"""Тесты хуков: прямой вызов с явным SessionState и CLI-подкоманда `hook`."""

from __future__ import annotations

import io
import json

import pytest

from appsecgate_mcp import hooks, server


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Изолирует домашний каталог и кэш Trivy, чтобы хуки не трогали реальные данные."""
    monkeypatch.setenv("APPSECGATE_MCP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(tmp_path / "trivy"))
    return tmp_path


async def test_session_start_direct(isolated_env):
    state = server.SessionState()
    out = await hooks.session_start(state, str(isolated_env))

    assert out["status"] == "ready"
    assert out["project_path"] == str(isolated_env.resolve())
    assert isinstance(out["scanners"], list)
    await state.close()


async def test_pre_tool_use_direct_is_warn_only(isolated_env):
    state = server.SessionState()
    state.project_path = str(isolated_env)

    out = await hooks.pre_tool_use(state, "Edit", {"file_path": "a.py"})

    assert out["decision"] == "allow"
    assert out["reason"] == "local_gate_warn_only"
    assert out["scan_pending"] is True
    await state.close()


async def test_pre_tool_use_read_has_no_pending_scan(isolated_env):
    state = server.SessionState()
    state.project_path = str(isolated_env)

    out = await hooks.pre_tool_use(state, "Read", {"file_path": "a.py"})

    assert out["scan_pending"] is False
    await state.close()


async def test_post_tool_use_rejects_path_outside_project(isolated_env):
    state = server.SessionState()
    state.project_path = str(isolated_env)

    out = await hooks.post_tool_use(state, "Edit", {"file_path": "/etc/passwd"})

    assert out["status"] == "error"
    assert "outside project" in out["reason"]
    assert out["files"] == []
    await state.close()


async def test_post_tool_use_rejects_parent_traversal(isolated_env):
    state = server.SessionState()
    state.project_path = str(isolated_env)

    out = await hooks.post_tool_use(state, "Write", {"path": "../../etc/passwd"})

    assert out["status"] == "error"
    await state.close()


async def test_post_tool_use_skips_non_write_tool(isolated_env):
    state = server.SessionState()
    state.project_path = str(isolated_env)

    out = await hooks.post_tool_use(state, "Read", {"file_path": "a.py"})

    assert out["status"] == "skipped"
    await state.close()


def test_cli_session_start_returns_json(isolated_env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    code = hooks.hook_main(["session_start", "--project", str(isolated_env)])

    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ready"


def test_cli_pre_tool_use_returns_json(isolated_env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Edit"})))

    code = hooks.hook_main(["pre_tool_use", "--project", str(isolated_env)])

    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "allow"


def test_cli_invalid_json_returns_error_json(isolated_env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))

    hooks.hook_main(["pre_tool_use", "--project", str(isolated_env)])

    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error"


def test_main_dispatches_hook_subcommand(isolated_env, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["appsecgate-mcp", "hook", "pre_tool_use"])
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    with pytest.raises(SystemExit) as exc:
        server.main()

    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "allow"
