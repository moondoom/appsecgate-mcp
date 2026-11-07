from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.guided import triage_guided
from appsecgate_mcp.agent.llm import LlmTimeoutError
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


def _response(calls=(), finish_reason="tool_calls"):
    message = _message(
        {"role": "assistant", "content": None, "tool_calls": [call._raw for call in calls]},
        list(calls),
    )
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

    async def __call__(self, name, arguments):
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


async def _run(tmp_path, backend, **overrides):
    controller = AgentController(backend)
    await controller.initialize("full")
    if "modes" in overrides:
        controller.finding_modes = overrides.pop("modes")
    return await triage_guided(_config(tmp_path, **overrides), controller)


def test_guided_groups_prompts_by_mode_and_telemetry_lane(monkeypatch, tmp_path):
    backend = _Backend(["fp-sast", "fp-cve", "fp-iac"])
    seen = []

    def fake_request(config, messages, tools, num_ctx=None):
        payload = json.loads(messages[1]["content"])
        seen.append(
            (num_ctx, messages[0]["content"], [item["finding_id"] for item in payload["findings"]])
        )
        return _response([_submit(payload["findings"][0]["finding_id"])])

    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", fake_request)
    modes = {"fp-sast": "sast", "fp-cve": "cve", "fp-iac": "iac"}
    result = asyncio.run(_run(tmp_path, backend, modes=modes))

    assert (
        result.usage["missing"],
        result.usage["agent_mode"],
        result.usage["batch_sort"],
        result.usage["internal_parallel"],
    ) == (0, "guided", "mode_major", 2)
    assert [item[0] for item in seen] == [32768, 32768, 32768]
    assert [item[2] for item in seen] == [["fp-cve"], ["fp-iac"], ["fp-sast"]]
    assert [proto in item[1] for proto, item in zip(("CVE", "IaC", "SAST"), seen, strict=True)] == [
        True
    ] * 3
    assert any(key.startswith("lane_") for key in result.usage)


def test_guided_batch_sort_none_preserves_inventory_order(monkeypatch, tmp_path):
    seen = []

    def fake_request(config, messages, tools, num_ctx=None):
        finding_id = json.loads(messages[1]["content"])["findings"][0]["finding_id"]
        seen.append(finding_id)
        return _response([_submit(finding_id)])

    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", fake_request)
    modes = {"fp-sast": "sast", "fp-cve": "cve", "fp-iac": "iac"}
    backend = _Backend(list(modes))
    result = asyncio.run(
        _run(tmp_path, backend, modes=modes, batch_sort="none", llm_max_tokens=200)
    )

    assert result.usage["missing"] == 0
    assert seen == ["fp-sast", "fp-cve", "fp-iac"]


def test_guided_internal_parallel_overlaps_batches(monkeypatch, tmp_path):
    both_started = threading.Event()
    entered = 0
    lock = threading.Lock()

    def fake_request(config, messages, tools, num_ctx=None):
        nonlocal entered
        finding_id = json.loads(messages[1]["content"])["findings"][0]["finding_id"]
        with lock:
            entered += 1
            if entered == 2:
                both_started.set()
        assert both_started.wait(2)
        return _response([_submit(finding_id)])

    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", fake_request)
    result = asyncio.run(_run(tmp_path, _Backend(["fp-1", "fp-2"]), llm_max_tokens=200))

    assert result.usage["missing"] == 0
    assert result.usage["internal_parallel"] == 2
    assert entered == 2


def test_guided_timeout_is_batch_fatal_and_terminal_after_retries(monkeypatch, tmp_path):
    calls = 0

    def fake_request(config, messages, tools, num_ctx=None):
        nonlocal calls
        calls += 1
        assert config.llm_failure_timeout == 600
        raise LlmTimeoutError("request timed out")

    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", fake_request)
    result = asyncio.run(_run(tmp_path, _Backend(["fp-1", "fp-2"])))

    assert calls > 1
    assert result.usage["missing"] == 0
    assert result.usage["failed_findings"] == 0
    assert result.usage["model_failed_findings"] == 2
    assert result.usage["model_failed_timeout"] == 2
    assert result.usage["timed_out_calls"] == calls
    assert {item.failure_reason for item in result.verdicts} == {"timeout"}


def test_guided_preflight_overflow_is_terminal_without_llm_call(monkeypatch, tmp_path):
    calls = 0

    def fake_request(config, messages, tools, num_ctx=None):
        nonlocal calls
        calls += 1
        raise AssertionError("LLM must not be called on pre-send overflow")

    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", fake_request)
    result = asyncio.run(_run(tmp_path, _Backend(["fp-1"]), llm_num_ctx=100, llm_max_tokens=10))

    assert calls == 0
    assert result.usage["failed_findings"] == 0
    assert result.usage["model_failed_findings"] == 1
    assert result.usage["model_failed_context_overflow"] == 1
    (verdict,) = result.verdicts
    assert verdict.verdict == "NEEDS_REVIEW"
    assert verdict.failure_reason == "context_overflow"
    assert "num_ctx=100" in (verdict.failure_detail or "")


def test_guided_preflight_overflow_splits_batch(monkeypatch, tmp_path):
    seen = []

    def fake_request(config, messages, tools, num_ctx=None):
        finding_id = json.loads(messages[1]["content"])["findings"][0]["finding_id"]
        seen.append(finding_id)
        return _response([_submit(finding_id)])

    def fake_estimate(messages, tools):
        if len(messages) < 2:
            return 0
        payload = json.loads(messages[1]["content"])
        return 1000 * len(payload["findings"])

    monkeypatch.setattr("appsecgate_mcp.agent.guided._request", fake_request)
    monkeypatch.setattr("appsecgate_mcp.agent.guided._estimate_request_tokens", fake_estimate)
    result = asyncio.run(
        _run(
            tmp_path,
            _Backend(["fp-1", "fp-2"]),
            llm_num_ctx=1800,
            llm_max_tokens=480,
        )
    )

    assert sorted(seen) == ["fp-1", "fp-2"]
    assert result.usage["missing"] == 0
    assert result.usage["model_failed_findings"] == 0
    assert result.usage["batch_retries"] >= 1
