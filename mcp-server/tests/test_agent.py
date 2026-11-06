from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from appsecgate_mcp.agent.cli import agent_main
from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.llm import LlmError, triage
from appsecgate_mcp.agent.models import AgentConfig, Verdict
from appsecgate_mcp.agent.runner import AgentError
from appsecgate_mcp.models.finding import Category, Finding, ScanResult, Severity
from appsecgate_mcp.server.session import SessionState
from appsecgate_mcp.server.tools.inventory import _scan_findings_page


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


def test_agent_reads_llm_generation_parameters(monkeypatch, tmp_path):
    captured = {}

    async def fake_run(config):
        captured.update(
            temperature=config.llm_temperature,
            top_p=config.llm_top_p,
            max_tokens=config.llm_max_tokens,
            num_ctx=config.llm_num_ctx,
        )
        return _report(config)

    monkeypatch.setattr("appsecgate_mcp.agent.cli.run_agent", fake_run)
    monkeypatch.setenv("APPSECGATE_LLM_TEMPERATURE", "0.2")
    monkeypatch.setenv("APPSECGATE_LLM_TOP_P", "0.9")
    monkeypatch.setenv("APPSECGATE_LLM_MAX_TOKENS", "1024")
    monkeypatch.setenv("APPSECGATE_LLM_NUM_CTX", "8192")

    assert agent_main(_args(tmp_path)) == 0
    assert captured == {
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 1024,
        "num_ctx": 8192,
    }


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


class _Message:
    def __init__(self, payload, tool_calls):
        self._payload = payload
        self.tool_calls = tool_calls

    def model_dump(self, *, exclude_none=False):
        return self._payload


def _call(name, arguments, call_id="call-1"):
    raw = {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
        _raw=raw,
    )


def _response(calls=(), *, tokens=10):
    calls = list(calls)
    payload = {
        "role": "assistant",
        "content": None,
        "tool_calls": [call._raw for call in calls],
    }
    message = _Message(payload, calls)
    usage = SimpleNamespace(
        model_dump=lambda mode: {
            "prompt_tokens": tokens // 2,
            "completion_tokens": tokens // 2,
            "total_tokens": tokens,
        }
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


async def _inventory_call(name, arguments):
    assert name == "get_scan_findings"
    return {
        "status": "ok",
        "finding_ids": ["fp-1", "fp-2"],
        "inventory_hash": "hash-1",
        "findings": [
            {"finding_id": "fp-1", "rule_id": "rule-1"},
            {"finding_id": "fp-2", "rule_id": "rule-2"},
        ],
        "next_cursor": None,
        "total": 2,
    }


def test_triage_autonomous_tools_cover_inventory(monkeypatch, tmp_path):
    responses = iter(
        [
            _response([_call("get_finding_batch", "{}")]),
            _response(
                [
                    _call(
                        "submit_verdicts",
                        json.dumps(
                            {
                                "verdicts": [
                                    {
                                        "finding_id": "fp-1",
                                        "verdict": "TRUE_POSITIVE",
                                        "explanation": "confirmed",
                                    },
                                    {
                                        "finding_id": "fp-2",
                                        "verdict": "FALSE_POSITIVE",
                                        "explanation": "example only",
                                    },
                                ]
                            }
                        ),
                        "call-2",
                    )
                ],
                tokens=20,
            ),
            _response(),
        ]
    )
    monkeypatch.setattr("appsecgate_mcp.agent.llm._request", lambda *args: next(responses))

    async def run():
        controller = AgentController(_inventory_call)
        await controller.initialize("full")
        return await triage(_config(tmp_path), controller)

    result = asyncio.run(run())

    assert [item.finding_id for item in result.verdicts] == ["fp-1", "fp-2"]
    assert result.usage["assigned"] == 2
    assert result.usage["missing"] == 0
    assert result.usage["total_tokens"] == 40
    assert result.usage["iterations"] == 3


def test_triage_reminds_about_pending_ids(monkeypatch, tmp_path):
    responses = iter(
        [
            _response(),
            _response(
                [
                    _call(
                        "submit_verdicts",
                        json.dumps(
                            {
                                "verdicts": [
                                    {
                                        "finding_id": "fp-1",
                                        "verdict": "NEEDS_REVIEW",
                                        "explanation": "uncertain",
                                    },
                                    {
                                        "finding_id": "fp-2",
                                        "verdict": "NEEDS_REVIEW",
                                        "explanation": "uncertain",
                                    },
                                ]
                            }
                        ),
                    )
                ]
            ),
            _response(),
        ]
    )
    captured = []

    def fake_request(config, messages, tools):
        captured.extend(messages)
        return next(responses)

    monkeypatch.setattr("appsecgate_mcp.agent.llm._request", fake_request)

    async def run():
        controller = AgentController(_inventory_call)
        await controller.initialize("full")
        return await triage(_config(tmp_path), controller)

    result = asyncio.run(run())

    assert result.usage["missing"] == 0
    assert any(
        isinstance(item.get("content"), str) and '"pending_total": 2' in item["content"]
        for item in captured
    )


def test_triage_iteration_limit_leaves_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("appsecgate_mcp.agent.llm._request", lambda *args: _response())

    async def run():
        controller = AgentController(_inventory_call)
        await controller.initialize("full")
        return await triage(_config(tmp_path, max_iterations=1), controller)

    result = asyncio.run(run())

    assert result.verdicts == []
    assert result.usage["missing"] == 2
    assert result.usage["iteration_limit_reached"] == 1


def test_scan_findings_pages_contain_full_inventory():
    state = SessionState()
    result = ScanResult(
        findings=[
            Finding(
                fingerprint=f"fp-{index:03d}",
                rule_id="rule",
                severity=Severity.HIGH,
                file_path="a.py",
                scanner="semgrep",
                category=Category.SAST,
            )
            for index in range(120)
        ]
    )
    state.register(result)

    first = _scan_findings_page(state, scope="file", cursor=0, limit=50)
    second = _scan_findings_page(state, scope="file", cursor=50, limit=50)
    third = _scan_findings_page(state, scope="file", cursor=100, limit=50)

    assert len(first["finding_ids"]) == 120
    assert [len(page["findings"]) for page in (first, second, third)] == [50, 50, 20]
    assert first["inventory_hash"] == third["inventory_hash"]
    assert third["next_cursor"] is None


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
    assert report["inventory"] == {
        "total": 0,
        "hash": report["inventory"]["hash"],
        "missing_ids": [],
    }
    assert report["GateSummary"]["should_fail"] is False
    assert [item["tool"] for item in report["action_log"]] == [
        "scan_project",
        "get_scan_findings",
        "check_gate",
        "sync",
    ]


def test_agent_reads_reuse_ttl(monkeypatch, tmp_path):
    captured = {}

    async def fake_run(config):
        captured["reuse_ttl_seconds"] = config.reuse_ttl_seconds
        return _report(config)

    monkeypatch.setattr("appsecgate_mcp.agent.cli.run_agent", fake_run)
    monkeypatch.setenv("APPSECGATE_AGENT_REUSE_TTL", "1h")

    assert agent_main(_args(tmp_path)) == 0
    assert captured["reuse_ttl_seconds"] == 3600


def test_scan_findings_include_unavailable_rule_provenance():
    state = SessionState()
    finding = Finding(
        fingerprint="fp-1",
        rule_id="CVE-2026-0001",
        severity=Severity.HIGH,
        file_path="requirements.txt",
        scanner="trivy",
        category=Category.SCA,
    )
    state.register(ScanResult(findings=[finding]))

    output = _scan_findings_page(state, scope="file", cursor=0, limit=1)

    assert output["findings"][0]["rule_hash"] is None
    assert output["findings"][0]["rule_hash_status"] == "unavailable"
