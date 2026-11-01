from __future__ import annotations

import json

import pytest

from appsecgate_mcp.agent.cli import agent_main
from appsecgate_mcp.agent.llm import LlmError, triage
from appsecgate_mcp.agent.models import AgentConfig, LlmResult, Verdict
from appsecgate_mcp.agent.runner import AgentError


def test_verdict_accepts_structured_patch():
    verdict = Verdict(
        finding_id="fp-1",
        verdict="TRUE_POSITIVE",
        patch=[{"file_path": "a.py", "start_line": 1, "end_line": 1, "new_code": "x = 2"}],
    )

    assert verdict.patch[0]["file_path"] == "a.py"


def _config(tmp_path, **overrides):
    values = {
        "project": tmp_path,
        "data_dir": tmp_path / "data",
        "llm_url": "http://llm.test/v1",
        "llm_model": "test-model",
        "no_sync": True,
    }
    values.update(overrides)
    return AgentConfig(**values)


def _report(config, should_fail=False):
    return {
        "run_id": config.run_id,
        "mode": "ro",
        "model": config.llm_model,
        "findings": [],
        "verdicts": [],
        "patches": [],
        "GateSummary": {"should_fail": should_fail},
        "action_log": [],
        "usage": {},
        "warnings": [],
        "duration_sec": 0.1,
        "exit_reason": "gate_block" if should_fail else "report_generated",
    }


def _args(tmp_path):
    return [
        "--project",
        str(tmp_path),
        "--data-dir",
        str(tmp_path / "data"),
        "--llm-url",
        "http://llm.test/v1",
        "--llm-model",
        "test-model",
        "--no-sync",
        "--output-format",
        "json",
    ]


def test_agent_gate_block_is_success(monkeypatch, tmp_path, capsys):
    async def fake_run(config):
        return _report(config, should_fail=True)

    monkeypatch.setattr("appsecgate_mcp.agent.cli.run_agent", fake_run)

    assert agent_main(_args(tmp_path)) == 0
    assert json.loads(capsys.readouterr().out)["exit_reason"] == "gate_block"


def test_agent_llm_failure_is_exit_2(monkeypatch, tmp_path, capsys):
    async def fake_run(config):
        raise LlmError("invalid protocol")

    monkeypatch.setattr("appsecgate_mcp.agent.cli.run_agent", fake_run)

    assert agent_main(_args(tmp_path)) == 2
    assert json.loads(capsys.readouterr().out)["exit_reason"] == "llm_error"


def test_agent_wrapped_llm_failure_is_exit_2(monkeypatch, tmp_path, capsys):
    async def fake_run(config):
        raise ExceptionGroup("MCP context", [LlmError("request timed out")])

    monkeypatch.setattr("appsecgate_mcp.agent.cli.run_agent", fake_run)

    assert agent_main(_args(tmp_path)) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["exit_reason"] == "llm_error"
    assert output["error"] == "request timed out"


def test_agent_sync_failure_is_exit_2(monkeypatch, tmp_path):
    async def fake_run(config):
        return _report(config)

    monkeypatch.setattr("appsecgate_mcp.agent.cli.run_agent", fake_run)
    monkeypatch.setattr("appsecgate_mcp.agent.cli._sync", lambda config: 1)

    assert agent_main(_args(tmp_path) + ["--master-url", "http://master.test"]) == 2


def test_triage_batches_each_finding_and_sums_usage(monkeypatch, tmp_path):
    config = _config(tmp_path)

    def fake_request(_config, payload):
        finding_id = payload["contexts"][0]["finding"]["fingerprint"]
        return LlmResult(
            verdicts=[Verdict(finding_id=finding_id, verdict="TRUE_POSITIVE")],
            usage={"total_tokens": 10},
        )

    monkeypatch.setattr("appsecgate_mcp.agent.llm._request", fake_request)
    contexts = [{"finding": {"fingerprint": value}} for value in ("fp-1", "fp-2")]

    import asyncio

    result = asyncio.run(triage(config, contexts))

    assert [item.finding_id for item in result.verdicts] == ["fp-1", "fp-2"]
    assert result.usage["total_tokens"] == 20


def test_triage_rejects_unknown_verdict_id(monkeypatch, tmp_path):
    config = _config(tmp_path)
    result = LlmResult(verdicts=[Verdict(finding_id="other", verdict="FALSE_POSITIVE")])
    monkeypatch.setattr("appsecgate_mcp.agent.llm._request", lambda *args: result)
    contexts = [{"finding": {"fingerprint": "expected"}}]

    with pytest.raises(LlmError, match="do not match"):
        import asyncio

        asyncio.run(triage(config, contexts))


def test_agent_mcp_failure_is_exit_2(monkeypatch, tmp_path, capsys):
    async def fake_run(config):
        raise AgentError("child unavailable")

    monkeypatch.setattr("appsecgate_mcp.agent.cli.run_agent", fake_run)

    assert agent_main(_args(tmp_path)) == 2
    assert json.loads(capsys.readouterr().out)["exit_reason"] == "infrastructure_error"


def test_agent_real_mcp_child_empty_project(tmp_path, capsys):
    (tmp_path / "README.md").write_text("empty project\n", encoding="utf-8")

    assert agent_main(_args(tmp_path)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["findings"] == []
    assert report["GateSummary"]["should_fail"] is False
    assert [item["tool"] for item in report["action_log"]] == [
        "scan_project",
        "check_gate",
        "sync",
    ]
