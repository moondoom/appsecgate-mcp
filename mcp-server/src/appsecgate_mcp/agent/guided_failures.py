from __future__ import annotations

from typing import Any

from appsecgate_mcp.agent.controller import AgentController


async def mark_model_failed(
    controller: AgentController,
    stats: dict[str, Any],
    remaining: list[str],
    *,
    reason: str,
    detail: str,
) -> None:
    result = await controller.execute(
        "submit_verdicts",
        {
            "verdicts": [
                {
                    "finding_id": finding_id,
                    "verdict": "NEEDS_REVIEW",
                    "explanation": "Model failed to judge this finding after retry/split.",
                    "failure_reason": reason,
                    "failure_detail": detail,
                }
                for finding_id in remaining
            ]
        },
    )
    accepted = result.get("accepted", 0)
    stats["model_failed_findings"] += accepted
    stats[f"model_failed_{reason}"] += accepted
    if result.get("errors"):
        stats["failed_findings"] += len(result["errors"])
