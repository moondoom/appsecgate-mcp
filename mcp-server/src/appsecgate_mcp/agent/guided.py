from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any

from appsecgate_mcp.agent.call_journal import CallJournal
from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.guided_failures import mark_model_failed
from appsecgate_mcp.agent.guided_ledger import charge_reserved, write_reserved_ledger
from appsecgate_mcp.agent.guided_payload import _build_payload
from appsecgate_mcp.agent.llm import (
    LlmError,
    LlmTimeoutError,
    _add_usage,
    _message,
    _project_context,
    _request,
    _response_usage,
)
from appsecgate_mcp.agent.models import AgentConfig, LlmResult
from appsecgate_mcp.agent.reuse import reuse_prior_verdicts

_MAX_SPLIT_DEPTH = 5
_MAX_BATCH_ITERATIONS = 4
_LANE_TELEMETRY_BUCKETS = (8192, 16384)
# Weighted-average estimator (chars/token) per owner decision; exact model
# tokenization is deferred to GD-16.
_CHARS_PER_TOKEN = 3
_OUTPUT_SAFETY_MARGIN = 256
# GD-13 (ADR-0019 Part 7): master tools removed from guided after measuring
# ~0 calls across 40 runs; read_project_file is gated by APPSECGATE_MODE_B.
_EVIDENCE_TOOLS = {"submit_verdicts"}
_MODE_B_TOOLS = {"read_project_file"}


def _guided_tools(config: AgentConfig, controller: AgentController) -> list[dict[str, Any]]:
    allowed = _EVIDENCE_TOOLS | (_MODE_B_TOOLS if config.mode_b else set())
    return [tool for tool in controller.tool_schemas() if tool["function"]["name"] in allowed]


def _batch_size(config: AgentConfig) -> int:
    return max(1, min(20, (config.llm_max_tokens // 2) // 120))


def _batch_size_for_mode(config: AgentConfig, mode: str) -> int:
    return max(1, config.mode_batch_sizes.get(mode) or _batch_size(config))


def _request_budget(config: AgentConfig, chunk_size: int) -> int:
    if not config.adaptive_max_tokens:
        return config.llm_max_tokens
    return min(config.adaptive_max_tokens_cap, chunk_size * 150 + 256)


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _verdict_arguments(message: Any) -> dict[str, Any] | None:
    for call in getattr(message, "tool_calls", None) or []:
        if call.function.name != "submit_verdicts":
            continue
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            return None
        return arguments if isinstance(arguments, dict) else None
    content = getattr(message, "content", None) or ""
    if "verdicts" not in content:
        return None
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) and "verdicts" in value else None


def _estimate_request_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    chars = len(json.dumps(messages, ensure_ascii=False, default=str))
    chars += len(json.dumps(tools, ensure_ascii=False, default=str))
    return -(-chars // _CHARS_PER_TOKEN)


def _telemetry_lane(config: AgentConfig, payload: dict[str, Any]) -> int:
    estimate = _estimate_request_tokens([{"role": "user", "content": payload}], [])
    for lane in (*_LANE_TELEMETRY_BUCKETS, config.llm_num_ctx):
        if estimate <= lane:
            return lane
    return config.llm_num_ctx


async def _triage_chunk(
    config: AgentConfig,
    controller: AgentController,
    tools: list[dict[str, Any]],
    project_context: dict[str, str],
    chunk: list[str],
    findings: dict[str, dict[str, Any]],
    usage: dict[str, Any],
    stats: dict[str, Any],
    call_journal: CallJournal,
    reserved: dict[str, int],
    depth: int,
    payload: dict[str, Any] | None = None,
    failure_reason: str | None = None,
    failure_detail: str | None = None,
) -> None:
    chunk = [fid for fid in chunk if fid in controller.pending]
    if not chunk:
        return
    stats["batches"] += 1
    if payload is None:
        payload = await _build_payload(controller, project_context, chunk, findings)
    lane = _telemetry_lane(config, payload)
    stats[f"lane_{lane}"] = stats.get(f"lane_{lane}", 0) + 1
    modes = {controller.finding_modes.get(finding_id, "sast") for finding_id in chunk}
    batch_id = hashlib.sha256(",".join(sorted(chunk)).encode()).hexdigest()[:16]
    mode = sorted(modes)[0]
    messages = [
        {"role": "system", "content": config.system_prompt_for_modes(modes)},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]
    prompt_estimate = _estimate_request_tokens(messages, tools)
    request_budget = _request_budget(config, len(chunk))
    reserve = request_budget + _OUTPUT_SAFETY_MARGIN
    if prompt_estimate + reserve > config.llm_num_ctx:
        detail = (
            f"est_prompt_tokens={prompt_estimate} + reserve={reserve} "
            f"> num_ctx={config.llm_num_ctx}"
        )
        if len(chunk) > 1 and depth < _MAX_SPLIT_DEPTH:
            stats["batch_retries"] += 1
            middle = len(chunk) // 2
            for part in (chunk[:middle], chunk[middle:]):
                await _triage_chunk(
                    config,
                    controller,
                    tools,
                    project_context,
                    part,
                    findings,
                    usage,
                    stats,
                    call_journal,
                    reserved,
                    depth + 1,
                )
            return
        await mark_model_failed(controller, stats, chunk, reason="context_overflow", detail=detail)
        return
    arguments = None
    truncated = False
    for _ in range(_MAX_BATCH_ITERATIONS):
        started_at = datetime.now(UTC)
        started = time.monotonic()
        call_usage: dict[str, Any] | None = None
        charge_reserved(reserved, chunk, prompt_estimate + reserve)
        try:
            response = await asyncio.to_thread(_request, config, messages, tools, request_budget)
        except LlmTimeoutError as exc:
            stats["timed_out_calls"] += 1
            failure_reason = "timeout"
            failure_detail = str(exc)[:500]
            response = None
        except LlmError as exc:
            failure_reason = "llm_error"
            failure_detail = str(exc)[:500]
            response = None
        if response is not None:
            call_usage = _response_usage(response)
        call_journal.append(
            batch_id=batch_id,
            mode=mode,
            started_monotonic=started,
            ended_monotonic=time.monotonic(),
            started_at=started_at,
            usage=call_usage,
            failure_reason=None if response is not None else failure_reason,
            failure_detail=None if response is not None else failure_detail,
        )
        if response is None:
            break
        _add_usage(usage, response)
        message = _message(response)
        truncated = getattr(response.choices[0], "finish_reason", None) == "length"
        if truncated:
            break
        arguments = _verdict_arguments(message)
        if arguments is not None:
            break
        evidence_calls = [
            call
            for call in getattr(message, "tool_calls", None) or []
            if call.function.name != "submit_verdicts"
        ]
        if not evidence_calls:
            break
        messages.append(message.model_dump(exclude_none=True))
        for call in evidence_calls:
            try:
                call_arguments = json.loads(call.function.arguments or "{}")
                if not isinstance(call_arguments, dict):
                    call_arguments = {}
            except json.JSONDecodeError:
                call_arguments = {}
            result = await controller.execute(call.function.name, call_arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.function.name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )
        stats["evidence_reads"] += len(evidence_calls)
    accepted = 0
    if arguments is not None:
        result = await controller.execute("submit_verdicts", arguments)
        accepted = result.get("accepted", 0)
    remaining = [fid for fid in chunk if fid in controller.pending]
    if not remaining:
        return
    if truncated or arguments is None or accepted == 0:
        stats["batch_retries"] += 1
    if depth >= _MAX_SPLIT_DEPTH:
        reason = failure_reason or "llm_error"
        detail = failure_detail or "invalid or truncated LLM response after retries"
        await mark_model_failed(controller, stats, remaining, reason=reason, detail=detail)
        return
    if len(remaining) == 1:
        await _triage_chunk(
            config,
            controller,
            tools,
            project_context,
            remaining,
            findings,
            usage,
            stats,
            call_journal,
            reserved,
            depth + 1,
            failure_reason=failure_reason,
            failure_detail=failure_detail,
        )
        return
    middle = len(remaining) // 2
    for part in (remaining[:middle], remaining[middle:]):
        await _triage_chunk(
            config,
            controller,
            tools,
            project_context,
            part,
            findings,
            usage,
            stats,
            call_journal,
            reserved,
            depth + 1,
            failure_reason=failure_reason,
            failure_detail=failure_detail,
        )


async def _prepare_batches(
    config: AgentConfig,
    controller: AgentController,
    project_context: dict[str, str],
    findings: dict[str, dict[str, Any]],
    batch_size: int,
) -> list[tuple[str, int, str, list[str], dict[str, Any]]]:
    pending = [fid for fid in controller.finding_ids if fid in controller.pending]
    grouped: list[list[str]] = []
    if config.batch_sort == "none":
        grouped = _chunks(pending, batch_size)
    else:
        by_mode: dict[str, list[str]] = {}
        for finding_id in pending:
            mode = controller.finding_modes.get(finding_id, "sast")
            by_mode.setdefault(mode, []).append(finding_id)
        for mode in sorted(by_mode):
            grouped.extend(_chunks(by_mode[mode], _batch_size_for_mode(config, mode)))
    prepared = []
    for chunk in grouped:
        payload = await _build_payload(controller, project_context, chunk, findings)
        mode = controller.finding_modes.get(chunk[0], "sast")
        lane = _telemetry_lane(config, payload)
        prepared.append((mode, lane, min(chunk), chunk, payload))
    if config.batch_sort == "mode_major":
        prepared.sort(key=lambda item: (item[0], item[1], item[2]))
    return prepared


async def triage_guided(config: AgentConfig, controller: AgentController) -> LlmResult:
    project_context = _project_context(config)
    tools = _guided_tools(config, controller)
    findings: dict[str, dict[str, Any]] = {}
    cursor = 0
    while True:
        page = await controller.call(
            "get_scan_findings",
            {"scope": controller.scope, "cursor": cursor, "limit": 50},
        )
        if page.get("status") != "ok":
            raise RuntimeError(f"get_scan_findings: {page.get('reason', 'failed')}")
        findings.update({item["finding_id"]: item for item in page["findings"]})
        if page["next_cursor"] is None:
            break
        cursor = page["next_cursor"]
    usage: dict[str, Any] = {}
    stats: dict[str, Any] = {
        "batches": 0,
        "batch_retries": 0,
        "failed_findings": 0,
        "model_failed_findings": 0,
        "model_failed_context_overflow": 0,
        "model_failed_timeout": 0,
        "model_failed_llm_error": 0,
        "model_failed_budget_exhausted": 0,
        "timed_out_calls": 0,
        "evidence_reads": 0,
    }
    await reuse_prior_verdicts(config, controller, stats)
    call_journal = CallJournal(config)
    reserved: dict[str, int] = {}
    batch_size = _batch_size(config)
    prepared = await _prepare_batches(config, controller, project_context, findings, batch_size)
    semaphore = asyncio.Semaphore(max(1, config.internal_parallel))

    async def _worker(chunk: list[str], payload: dict[str, Any]) -> None:
        async with semaphore:
            await _triage_chunk(
                config,
                controller,
                tools,
                project_context,
                chunk,
                findings,
                usage,
                stats,
                call_journal,
                reserved,
                0,
                payload=payload,
            )

    if prepared:
        await asyncio.gather(*(_worker(chunk, payload) for _, _, _, chunk, payload in prepared))
    stats.update(write_reserved_ledger(config, reserved))
    if call_journal.cache_metrics_unavailable:
        stats["cache_metrics_unavailable"] = 1
    result = controller.result()
    result.usage = {
        **usage,
        **result.usage,
        **stats,
        "agent_mode": "guided",
        "batch_size": batch_size,
        "batch_sort": config.batch_sort,
        "internal_parallel": config.internal_parallel,
        "failure_timeout_s": config.llm_failure_timeout,
        "mode_batch_sizes": config.mode_batch_sizes,
        "adaptive_max_tokens": int(config.adaptive_max_tokens),
        "iterations": stats["batches"],
    }
    if controller.pending:
        result.usage["guided_incomplete"] = 1
    return result
