from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.llm import LlmError, triage
from appsecgate_mcp.agent.models import AgentConfig


class _Message:
    def __init__(self, payload, tool_calls):
        self._payload = payload
        self.tool_calls = tool_calls

    def model_dump(self, *, exclude_none=False):
        return self._payload


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


def _response(calls=()):
    calls = list(calls)
    message = _Message(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [call._raw for call in calls],
        },
        calls,
    )
    usage = SimpleNamespace(model_dump=lambda mode: {"total_tokens": 5})
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _submit(*finding_ids):
    return _call(
        "submit_verdicts",
        json.dumps(
            {
                "verdicts": [
                    {
                        "finding_id": finding_id,
                        "verdict": "NEEDS_REVIEW",
                        "explanation": "review",
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
        "agent_mode": "free",
    }
    values.update(overrides)
    return AgentConfig(**values)


async def _inventory_call(name, arguments):
    assert name == "get_scan_findings"
    return {
        "status": "ok",
        "finding_ids": ["fp-1", "fp-2"],
        "inventory_hash": "hash-1",
        "findings": [{"finding_id": "fp-1"}, {"finding_id": "fp-2"}],
        "next_cursor": None,
        "total": 2,
    }


def test_loop_restarts_from_checkpoint_without_losing_verdicts(monkeypatch, tmp_path):
    responses = iter(
        [
            _response([_submit("fp-1")]),
            _response([_call("get_finding_batch", "{}")]),
            _response([_call("get_finding_batch", "{}")]),
            _response([_call("get_finding_batch", "{}")]),
            _response([_submit("fp-2")]),
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

    assert [item.finding_id for item in result.verdicts] == ["fp-1", "fp-2"]
    assert result.usage["loops"] == 1
    assert result.usage["restarts"] == 1
    assert result.usage["missing"] == 0
    assert any(
        isinstance(item.get("content"), str) and '"reason": "loop_restart"' in item["content"]
        for item in captured
    )


def test_restart_limit_leaves_pending(monkeypatch, tmp_path):
    responses = iter([_response([_call("get_finding_batch", "{}")]) for _ in range(3)])
    monkeypatch.setattr("appsecgate_mcp.agent.llm._request", lambda *args: next(responses))

    async def run():
        controller = AgentController(_inventory_call)
        await controller.initialize("full")
        return await triage(_config(tmp_path, max_restarts=0), controller)

    result = asyncio.run(run())

    assert result.verdicts == []
    assert result.usage["missing"] == 2
    assert result.usage["restart_limit_reached"] == 1


def test_context_compaction_preserves_pending_state(monkeypatch, tmp_path):
    async def large_inventory_call(name, arguments):
        result = await _inventory_call(name, arguments)
        result["padding"] = "x" * 5000
        return result

    responses = iter(
        [
            _response([_call("get_finding_batch", "{}")]),
            _response([_submit("fp-1", "fp-2")]),
            _response(),
        ]
    )
    monkeypatch.setattr("appsecgate_mcp.agent.llm._request", lambda *args: next(responses))

    async def run():
        controller = AgentController(large_inventory_call)
        await controller.initialize("full")
        return await triage(_config(tmp_path, max_context_chars=2000), controller)

    result = asyncio.run(run())

    assert result.usage["compactions"] == 1
    assert result.usage["missing"] == 0
    assert len(result.verdicts) == 2


def test_master_tools_pass_knowledge_cutoff():
    calls = []

    async def master_call(name, arguments):
        calls.append((name, arguments))
        if name == "describe_schema":
            return {"status": "ok", "views": {"v_cve": []}}
        return {"status": "ok", "rows": [], "row_count": 0}

    async def run():
        controller = AgentController(
            _inventory_call, master_call=master_call, knowledge_cutoff="2026-11-04T00:00:00Z"
        )
        schema = await controller.execute("master_describe_schema", {})
        result = await controller.execute(
            "master_query_findings_db", {"sql": "SELECT cve_id FROM v_cve"}
        )
        return schema, result

    schema, result = asyncio.run(run())

    assert schema["status"] == "ok"
    assert result["status"] == "ok"
    assert calls[1][1]["knowledge_cutoff"] == "2026-11-04T00:00:00Z"


def test_provider_repeat_limit_restarts_from_checkpoint(monkeypatch, tmp_path):
    responses = iter(
        [
            LlmError("prediction aborted, token repeat limit reached"),
            _response([_submit("fp-1", "fp-2")]),
            _response(),
        ]
    )

    def fake_request(*args):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("appsecgate_mcp.agent.llm._request", fake_request)

    async def run():
        controller = AgentController(_inventory_call)
        await controller.initialize("full")
        return await triage(_config(tmp_path), controller)

    result = asyncio.run(run())

    assert result.usage["provider_repeat_restarts"] == 1
    assert result.usage["restarts"] == 1
    assert result.usage["missing"] == 0
    assert len(result.verdicts) == 2
