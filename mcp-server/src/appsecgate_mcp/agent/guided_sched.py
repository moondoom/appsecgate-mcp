from __future__ import annotations

import asyncio
import json
from typing import Any

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.guided import (
    _batch_size,
    _chunks,
    _manifest_contents,
    _triage_chunk,
)
from appsecgate_mcp.agent.llm import _project_context
from appsecgate_mcp.agent.models import AgentConfig, LlmResult
from appsecgate_mcp.agent.reuse import reuse_prior_verdicts

_EVIDENCE_TOOLS = {
    "submit_verdicts",
    "read_project_file",
    "master_describe_schema",
    "master_query_findings_db",
}


async def triage_guided_sched(config: AgentConfig, controller: AgentController) -> LlmResult:
    project_context = _project_context(config)
    system = config.guided_prompt_path.read_text(encoding="utf-8")
    tools = [
        tool for tool in controller.tool_schemas() if tool["function"]["name"] in _EVIDENCE_TOOLS
    ]
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
    stats = {
        "batches": 0,
        "batch_retries": 0,
        "failed_findings": 0,
        "evidence_reads": 0,
        "lane_escalations": 0,
        "lane_underestimated": 0,
    }
    await reuse_prior_verdicts(config, controller, stats)
    batch_size = _batch_size(config)
    pending = [fid for fid in controller.finding_ids if fid in controller.pending]
    prepared: list[tuple[str, int, list[str], dict[str, Any]]] = []
    for chunk in _chunks(pending, batch_size):
        for mode in sorted({controller.finding_modes.get(fid, "sast") for fid in chunk}):
            mode_chunk = [fid for fid in chunk if controller.finding_modes.get(fid, "sast") == mode]
            contexts = await controller.call("get_fix_context_batch", {"finding_ids": mode_chunk})
            manifests = await _manifest_contents(controller, mode_chunk, findings)
            payload = {
                "task": "Submit one verdict for every provided finding ID.",
                "project_context": project_context,
                "findings": [findings[fid] for fid in mode_chunk if fid in findings],
                "contexts": contexts,
                "manifest_files": manifests,
            }
            estimate = len(json.dumps(payload, ensure_ascii=False, default=str)) // 3 + 4000
            lane_index = next(
                (i for i, lane in enumerate(config.sched_lanes) if estimate <= lane),
                len(config.sched_lanes) - 1,
            )
            prepared.append((mode, lane_index, mode_chunk, payload))
    prepared.sort(key=lambda item: (item[0], item[1]))
    semaphore = asyncio.Semaphore(max(1, config.sched_parallel))

    async def _worker(chunk: list[str], payload: dict[str, Any]) -> None:
        async with semaphore:
            await _triage_chunk(
                config,
                controller,
                system,
                tools,
                project_context,
                chunk,
                findings,
                usage,
                stats,
                0,
                lanes=config.sched_lanes,
                payload=payload,
            )

    if prepared:
        await asyncio.gather(*(_worker(chunk, payload) for _, _, chunk, payload in prepared))
    result = controller.result()
    result.usage = {
        **usage,
        **result.usage,
        **stats,
        "agent_mode": "guided-sched",
        "batch_size": batch_size,
        "iterations": stats["batches"],
        "sched_parallel": config.sched_parallel,
        "sched_lanes": config.sched_lanes,
    }
    if controller.pending:
        result.usage["guided_incomplete"] = 1
    return result
