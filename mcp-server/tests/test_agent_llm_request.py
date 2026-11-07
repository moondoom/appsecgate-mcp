from __future__ import annotations

from types import SimpleNamespace

import pytest

from appsecgate_mcp.agent.llm import LlmTimeoutError, _request
from appsecgate_mcp.agent.models import AgentConfig


def _config(tmp_path):
    return AgentConfig(
        project=tmp_path, data_dir=tmp_path / "data", llm_url="http://x", llm_model="m"
    )


def _client_class(completions):
    class _Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=completions)

    return _Client


class _Completions:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1 and self.error is not None:
            raise self.error
        return "ok"


def test_request_retries_transient_once(monkeypatch, tmp_path):
    class _StatusError(Exception):
        status_code = 502

    completions = _Completions(_StatusError("bad gateway"))
    monkeypatch.setattr(
        "appsecgate_mcp.agent.llm._load_openai", lambda: _client_class(completions)
    )
    monkeypatch.setattr("appsecgate_mcp.agent.llm.time.sleep", lambda seconds: None)

    assert _request(_config(tmp_path), [{"role": "user", "content": "hi"}], []) == "ok"
    assert completions.calls == 2


def test_request_never_retries_timeout(monkeypatch, tmp_path):
    completions = _Completions(TimeoutError("request timed out"))
    monkeypatch.setattr(
        "appsecgate_mcp.agent.llm._load_openai", lambda: _client_class(completions)
    )

    with pytest.raises(LlmTimeoutError):
        _request(_config(tmp_path), [{"role": "user", "content": "hi"}], [])
    assert completions.calls == 1
