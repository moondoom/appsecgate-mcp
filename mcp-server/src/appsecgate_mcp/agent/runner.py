from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.guided import triage_guided
from appsecgate_mcp.agent.journal import TriageJournal
from appsecgate_mcp.agent.llm import triage
from appsecgate_mcp.agent.master import MasterClient
from appsecgate_mcp.agent.models import AgentConfig
from appsecgate_mcp.agent.verdict_validator import finding_mode


class AgentError(RuntimeError):
    pass


def _data(result: Any) -> dict[str, Any]:
    if result.isError:
        text = "".join(getattr(item, "text", "") for item in result.content)
        raise AgentError(f"MCP tool failed: {text}")
    if result.structuredContent is not None:
        return result.structuredContent
    text = "".join(getattr(item, "text", "") for item in result.content)
    try:
        import json

        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise AgentError("MCP tool returned no structured result") from exc
    if not isinstance(value, dict):
        raise AgentError("MCP tool returned a non-object result")
    return value


async def _all_findings(call: Any, scope: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    cursor = 0
    while True:
        page = await call("get_scan_findings", {"scope": scope, "cursor": cursor, "limit": 50})
        if page.get("status") != "ok":
            raise AgentError(f"get_scan_findings: {page.get('reason', 'failed')}")
        findings.extend(page["findings"])
        if page["next_cursor"] is None:
            return findings
        cursor = page["next_cursor"]


async def run_agent(config: AgentConfig) -> dict[str, Any]:
    started = time.monotonic()
    action_log: list[dict[str, Any]] = []
    command = [sys.executable, "-m", "appsecgate_mcp", "serve", "--transport", "stdio"]
    command += ["--project", str(config.project.resolve())]
    if config.project_id:
        command += ["--project-id", config.project_id]
    env = dict(os.environ)
    env["APPSECGATE_DATA_DIR"] = str(config.data_dir)
    env["APPSECGATE_MCP_HOME"] = str(config.data_dir)
    parameters = StdioServerParameters(command=command[0], args=command[1:], env=env)

    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                tool_started = time.monotonic()
                result = _data(await session.call_tool(name, arguments))
                action_log.append(
                    {
                        "tool": name,
                        "status": "ok",
                        "duration_sec": round(time.monotonic() - tool_started, 3),
                    }
                )
                return result

            scan_name = "scan_project" if config.scan == "full" else "scan_diff"
            scan = await call(scan_name, {})
            if scan.get("error"):
                raise AgentError(f"{scan_name}: {scan['error']}")
            config.ruleset_hash = scan.get("meta", {}).get("ruleset_hash")
            master_client = None
            master_error = ""
            master_unavailable = False
            if config.master_url and config.master_api_key and not config.no_master_knowledge:
                try:
                    master_client = MasterClient(config.master_url, config.master_api_key)
                    await master_client.__aenter__()
                except Exception as exc:
                    master_client = None
                    master_unavailable = True
                    master_error = f"{type(exc).__name__}: {exc}"[:300]
            try:
                journal = TriageJournal(config, scan_meta=scan.get("meta", {}))
                controller = AgentController(
                    call,
                    journal=journal.append,
                    master_call=master_client.call if master_client else None,
                    knowledge_cutoff=config.knowledge_cutoff,
                )
                try:
                    await controller.initialize(config.scan)
                except RuntimeError as exc:
                    raise AgentError(str(exc)) from exc
                journal.project_id = controller.project_id
                findings = await _all_findings(call, config.scan) if controller.finding_ids else []
                journal.findings = {item["finding_id"]: item for item in findings}
                controller.finding_modes = {
                    item["finding_id"]: finding_mode(item.get("category")) for item in findings
                }
                controller.finding_snippets = {
                    item["finding_id"]: item.get("snippet") or "" for item in findings
                }
                if not controller.finding_ids:
                    llm = controller.result()
                elif config.agent_mode == "guided":
                    llm = await triage_guided(config, controller)
                else:
                    llm = await triage(config, controller)
            finally:
                if master_client is not None:
                    await master_client.__aexit__(None, None, None)
            gate = await call("check_gate", {"scope": config.scan, "policy": config.policy})

    usage = llm.usage
    if master_unavailable:
        usage["master_knowledge_unavailable"] = 1
    total_tokens = usage.get("total_tokens")
    budget_exceeded = isinstance(total_tokens, int) and total_tokens > config.max_tokens
    verdicts = [item.model_dump(mode="json") for item in llm.verdicts]
    warnings = []
    if master_unavailable:
        warnings.append(
            f"master knowledge is unavailable; local scanner facts only: {master_error}"
        )
    if controller.pending:
        warnings.append(f"{len(controller.pending)} findings have no model verdict")
    if budget_exceeded:
        warnings.append(f"LLM token budget exceeded: {total_tokens}>{config.max_tokens}")
    return {
        "run_id": config.run_id,
        "mode": config.mode,
        "agent_mode": config.agent_mode,
        "model": config.llm_model,
        "prompt_sha256": config.prompt_sha256,
        "scan_meta": scan.get("meta", {}),
        "inventory": {
            "total": len(controller.finding_ids),
            "hash": controller.inventory_hash,
            "missing_ids": controller.pending_ids,
        },
        "findings": findings,
        "verdicts": verdicts,
        "patches": [
            {"finding_id": item["finding_id"], "patch": item["patch"]}
            for item in verdicts
            if item["patch"]
        ],
        "GateSummary": gate,
        "action_log": [*action_log, *controller.action_log],
        "usage": usage,
        "warnings": warnings,
        "duration_sec": round(time.monotonic() - started, 3),
        "exit_reason": (
            "budget_partial"
            if budget_exceeded and controller.pending
            else "gate_block"
            if gate.get("should_fail")
            else "report_generated"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
    }
