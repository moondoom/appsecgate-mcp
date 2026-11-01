"""Markdown/NDJSON-представления результата server-agent."""

from __future__ import annotations

import json
from typing import Literal

from appsecgate_agent.runner import AgentResult


def render_markdown(result: AgentResult) -> str:
    gate = result.gate
    meta = gate.get("meta", {})
    lines = [
        "# AppSecGate report",
        "",
        f"- Should fail: `{str(gate.get('should_fail', False)).lower()}`",
        f"- Recommended action: `{gate.get('recommended_action', 'unknown')}`",
        f"- Scope: `{meta.get('scope', 'unknown')}`",
        f"- Policy: `{meta.get('policy', 'unknown')}`",
        f"- Blocked: `{len(gate.get('blocked_fps', []))}`",
        f"- Warned: `{len(gate.get('warned_fps', []))}`",
        "",
        "## Reasons",
        "",
    ]
    reasons = gate.get("by_reason", {})
    lines.extend(f"- `{reason}`: {count}" for reason, count in sorted(reasons.items()))
    blocked = gate.get("blocked_fps", [])
    if blocked:
        lines.extend(["", "## Blocked fingerprints", ""])
        lines.extend(f"- `{fp}`" for fp in blocked)
    return "\n".join(lines) + "\n"


def render_ndjson(result: AgentResult) -> str:
    payload = {
        "type": "appsecgate_report",
        "scan": result.scan,
        "gate": result.gate,
    }
    return json.dumps(payload, ensure_ascii=False) + "\n"


def render(result: AgentResult, output_format: Literal["markdown", "ndjson"]) -> str:
    if output_format == "ndjson":
        return render_ndjson(result)
    return render_markdown(result)
