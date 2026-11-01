from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from appsecgate_mcp.agent.llm import triage
from appsecgate_mcp.agent.models import AgentConfig, LlmResult


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
            findings = scan.get("top_findings", [])
            finding_ids = [item["finding_id"] for item in findings]
            contexts: list[dict[str, Any]] = []
            for offset in range(0, len(finding_ids), 20):
                batch = await call(
                    "get_fix_context_batch", {"finding_ids": finding_ids[offset : offset + 20]}
                )
                if batch.get("status") != "ok":
                    raise AgentError(f"get_fix_context_batch: {batch.get('reason', 'failed')}")
                contexts.extend(batch.get("contexts", []))
            llm = await triage(config, contexts) if contexts else LlmResult()
            gate = await call("check_gate", {"scope": config.scan, "policy": config.policy})

    usage = llm.usage
    total_tokens = usage.get("total_tokens")
    if isinstance(total_tokens, int) and total_tokens > config.max_tokens:
        raise AgentError(f"LLM token limit exceeded: {total_tokens}>{config.max_tokens}")
    verdicts = [item.model_dump(mode="json") for item in llm.verdicts]
    return {
        "run_id": config.run_id,
        "mode": config.mode,
        "model": config.llm_model,
        "prompt_sha256": config.prompt_sha256,
        "findings": findings,
        "verdicts": verdicts,
        "patches": [
            {"finding_id": item["finding_id"], "patch": item["patch"]}
            for item in verdicts
            if item["patch"]
        ],
        "GateSummary": gate,
        "action_log": action_log,
        "usage": usage,
        "warnings": [],
        "duration_sec": round(time.monotonic() - started, 3),
        "exit_reason": "gate_block" if gate.get("should_fail") else "report_generated",
        "generated_at": datetime.now(UTC).isoformat(),
    }
