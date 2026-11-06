from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.guided import _batch_size, triage_guided
from appsecgate_mcp.agent.guided_sched import triage_guided_sched
from appsecgate_mcp.agent.models import AgentConfig


def _message(payload, tool_calls):
    return SimpleNamespace(
        tool_calls=tool_calls,
        content=payload.get("content"),
        model_dump=lambda exclude_none=False: payload,
    )


def _call(name, arguments, call_id="call-1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
        _raw={
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        },
    )


def _response(calls=(), content=None, finish_reason="tool_calls"):
    payload = {"role": "assistant", "content": content, "tool_calls": [c._raw for c in calls]}
    message = _message(payload, list(calls))
    usage = SimpleNamespace(model_dump=lambda mode: {"total_tokens": 5})
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)], usage=usage
    )


def _submit(*finding_ids):
    return _call(
        "submit_verdicts",
        json.dumps(
            {
                "verdicts": [
                    {
                        "finding_id": finding_id,
                        "verdict": "FALSE_POSITIVE",
                        "explanation": "fixture",
                    }
                    for finding_id in finding_ids
                ]
            }
        ),
    )


def _config(tmp_path, **overrides):
    values = {
        "project": tmp_path,
        "data_dir": tmp_path / "data",
        "llm_url": "http://llm.test/v1",
        "llm_model": "test-model",
        "agent_mode": "guided",
    }
    values.update(overrides)
    return AgentConfig(**values)


class _Backend:
    def __init__(self, finding_ids):
        self.finding_ids = finding_ids
        self.calls = []

    async def __call__(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_scan_findings":
            ids = self.finding_ids
            return {
                "status": "ok",
                "finding_ids": ids,
                "inventory_hash": "hash-1",
                "findings": [{"finding_id": fid} for fid in ids],
                "next_cursor": None,
                "total": len(ids),
            }
        if name == "get_fix_context_batch":
            return {
                "status": "ok",
                "contexts": [{"finding_id": fid} for fid in arguments["finding_ids"]],
            }
        raise AssertionError(f"unexpected tool: {name}")


def _run(tmp_path, backend, responses, **overrides):
    async def run():
        controller = AgentController(backend)
        await controller.initialize("full")
        return await triage_guided(_config(tmp_path, **overrides), controller)

    return asyncio.run(run())


def test_batch_size_derives_from_output_budget(tmp_path):
    assert _batch_size(_config(tmp_path, llm_max_tokens=2048)) == 8
    assert _batch_size(_config(tmp_path, llm_max_tokens=8192)) == 20
    assert _batch_size(_config(tmp_path, llm_max_tokens=200)) == 1


def test_guided_completes_inventory_without_free_tools(monkeypatch, tmp_path):
    backend = _Backend(["fp-1", "fp-2", "fp-3"])
    responses = iter([_response([_submit("fp-1", "fp-2", "fp-3")])])
    seen_tools = []

    def fake_request(config, messages, tools, num_ctx=None):
        seen_tools.append(tools)
        return next(responses)

    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", fake_request)
    result = _run(tmp_path, backend, responses)

    assert result.usage["missing"] == 0
    assert result.usage["agent_mode"] == "guided"
    assert result.usage["batch_size"] == 8
    assert len(result.verdicts) == 3
    assert [[t["function"]["name"] for t in tools] for tools in seen_tools] == [
        ["read_project_file", "submit_verdicts"]
    ]
    assert {name for name, _ in backend.calls} == {"get_scan_findings", "get_fix_context_batch"}


def test_guided_truncated_batch_is_split_and_retried(monkeypatch, tmp_path):
    backend = _Backend(["fp-1", "fp-2"])
    responses = iter(
        [
            _response(content='{"verdicts": [{"finding_id": "fp-1"', finish_reason="length"),
            _response([_submit("fp-1")]),
            _response([_submit("fp-2")]),
        ]
    )
    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", lambda *args: next(responses))
    result = _run(tmp_path, backend, responses)

    assert result.usage["missing"] == 0
    assert result.usage["batch_retries"] == 1
    assert len(result.verdicts) == 2


def test_guided_content_json_fallback(monkeypatch, tmp_path):
    backend = _Backend(["fp-1"])
    content = json.dumps(
        {"verdicts": [{"finding_id": "fp-1", "verdict": "TRUE_POSITIVE", "explanation": "x"}]}
    )
    responses = iter([_response(content=content, finish_reason="stop")])
    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", lambda *args: next(responses))
    result = _run(tmp_path, backend, responses)

    assert result.usage["missing"] == 0
    assert result.verdicts[0].verdict == "TRUE_POSITIVE"


def test_guided_prefetches_manifest_files(monkeypatch, tmp_path):
    backend = _Backend(["fp-1", "fp-2"])

    async def inventory(name, arguments):
        if name == "get_scan_findings":
            result = await backend(name, arguments)
            result["findings"][0]["file_path"] = "requirements.txt"
            result["findings"][1]["file_path"] = "src/app.py"
            return result
        if name == "read_project_file":
            return {
                "status": "ok",
                "lines": [{"line": 1, "text": "pillow==9.0.0"}],
                "truncated": False,
            }
        return await backend(name, arguments)

    payloads = []

    def fake_request(config, messages, tools, num_ctx=None):
        payloads.append(json.loads(messages[1]["content"]))
        return _response([_submit("fp-1", "fp-2")])

    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", fake_request)

    async def run():
        controller = AgentController(inventory)
        await controller.initialize("full")
        return await triage_guided(_config(tmp_path), controller)

    result = asyncio.run(run())

    assert result.usage["missing"] == 0
    manifests = payloads[0]["manifest_files"]
    assert list(manifests) == ["requirements.txt"]
    assert "pillow==9.0.0" in manifests["requirements.txt"]["content"]


def test_guided_evidence_reads_before_submit(monkeypatch, tmp_path):
    backend = _Backend(["fp-1"])

    async def inventory(name, arguments):
        if name == "read_project_file":
            return {
                "status": "ok",
                "lines": [{"line": 7, "text": "shlex.quote(path)"}],
                "truncated": False,
            }
        return await backend(name, arguments)

    responses = iter(
        [
            _response([_call("read_project_file", '{"path": "src/app.py"}')]),
            _response([_submit("fp-1")]),
        ]
    )
    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", lambda *args: next(responses))

    async def run():
        controller = AgentController(inventory)
        await controller.initialize("full")
        return await triage_guided(_config(tmp_path), controller)

    result = asyncio.run(run())

    assert result.usage["missing"] == 0
    assert result.usage["evidence_reads"] == 1
    assert len(result.verdicts) == 1


def test_guided_evidence_loop_limit_fails_open(monkeypatch, tmp_path):
    backend = _Backend(["fp-1"])

    async def inventory(name, arguments):
        if name == "read_project_file":
            return {"status": "ok", "lines": [], "truncated": False}
        return await backend(name, arguments)

    monkeypatch.setattr(
        "appsecgate_mcp.agent.guided._request",
        lambda *args: _response([_call("read_project_file", '{"path": "src/app.py"}')]),
    )

    async def run():
        controller = AgentController(inventory)
        await controller.initialize("full")
        return await triage_guided(_config(tmp_path), controller)

    result = asyncio.run(run())

    assert result.usage["missing"] == 1
    assert result.usage["failed_findings"] == 1
    assert result.usage["evidence_reads"] == 4


def test_guided_partial_omission_retries_single_finding(monkeypatch, tmp_path):
    backend = _Backend(["fp-1", "fp-2"])
    responses = iter([_response([_submit("fp-1")]), _response([_submit("fp-2")])])
    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", lambda *args: next(responses))
    result = _run(tmp_path, backend, responses)

    assert result.usage["missing"] == 0
    assert result.usage["failed_findings"] == 0
    assert len(result.verdicts) == 2


def test_guided_unparseable_single_finding_left_pending(monkeypatch, tmp_path):
    backend = _Backend(["fp-1"])
    responses = iter([_response(content="garbage", finish_reason="stop")])
    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", lambda *args: next(responses))
    result = _run(tmp_path, backend, responses)

    assert result.usage["missing"] == 1
    assert result.usage["failed_findings"] == 1
    assert result.usage["guided_incomplete"] == 1
    assert result.verdicts == []


@pytest.mark.parametrize(
    ("triage_fn", "mode"),
    [(triage_guided, "guided"), (triage_guided_sched, "guided-sched")],
)
def test_guided_confidence_is_optional_and_validated(monkeypatch, tmp_path, triage_fn, mode):
    backend = _Backend(["fp-1", "fp-2", "fp-3"])
    verdicts = [
        {
            "finding_id": "fp-1",
            "verdict": "TRUE_POSITIVE",
            "explanation": "direct evidence",
            "confidence_level": "high",
            "evidence_basis": "direct_snippet",
            "evidence_quote": "dangerous(input)",
            "quote_hash": hashlib.sha256(b"dangerous(input)").hexdigest(),
        },
        {"finding_id": "fp-2", "verdict": "NEEDS_REVIEW", "explanation": "uncertain"},
        {
            "finding_id": "fp-3",
            "verdict": "TRUE_POSITIVE",
            "explanation": "pattern only",
            "confidence_level": "high",
            "evidence_basis": "indirect_pattern",
            "evidence_quote": "pattern",
            "quote_hash": "hash-3",
        },
    ]
    responses = iter([_response([_call("submit_verdicts", json.dumps({"verdicts": verdicts}))])])
    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", lambda *args: next(responses))

    async def run():
        controller = AgentController(backend)
        await controller.initialize("full")
        return await triage_fn(_config(tmp_path, agent_mode=mode), controller)

    result = asyncio.run(run())

    assert result.usage["missing"] == 0
    assert result.usage["failed_findings"] == 0
    assert [item.confidence_level for item in result.verdicts] == ["high", None, "medium"]
    assert result.verdicts[2].downgrade_reason == "basis_not_high_capable"


def test_guided_sched_groups_prompts_by_mode_and_lane(monkeypatch, tmp_path):
    backend = _Backend(["fp-sast", "fp-cve", "fp-iac"])
    seen = []

    def fake_request(config, messages, tools, num_ctx=None):
        payload = json.loads(messages[1]["content"])
        seen.append((messages[0]["content"], [item["finding_id"] for item in payload["findings"]]))
        finding_id = payload["findings"][0]["finding_id"]
        return _response([_submit(finding_id)])

    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", fake_request)

    async def run():
        controller = AgentController(backend)
        await controller.initialize("full")
        controller.finding_modes = {"fp-sast": "sast", "fp-cve": "cve", "fp-iac": "iac"}
        return await triage_guided_sched(_config(tmp_path, agent_mode="guided-sched"), controller)

    result = asyncio.run(run())

    assert result.usage["missing"] == 0
    assert [ids for _, ids in seen] == [["fp-cve"], ["fp-iac"], ["fp-sast"]]
    assert "CVE evidence protocol" in seen[0][0]
    assert "IaC evidence protocol" in seen[1][0]
    assert "SAST evidence protocol" in seen[2][0]
