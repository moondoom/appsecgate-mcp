from __future__ import annotations

import hashlib
from typing import Any

from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.session import SessionState
from appsecgate_mcp.server.tools.common import ensure_session
from appsecgate_mcp.server.tools.scan import _mark_shown


def _scan_findings_page(
    state: SessionState, *, scope: str, cursor: int, limit: int
) -> dict[str, Any]:
    result = state.last_results.get(scope)
    if result is None:
        return {"status": "error", "reason": f"no scan result for scope: {scope}"}
    ordered = sorted(result.findings, key=lambda item: item.fingerprint)
    finding_ids = [item.fingerprint for item in ordered]
    inventory_hash = hashlib.sha256("\n".join(finding_ids).encode()).hexdigest()
    page = ordered[cursor : cursor + limit]
    next_cursor = cursor + len(page)
    return {
        "status": "ok",
        "scope": scope,
        "project_id": state.project_id,
        "total": len(ordered),
        "finding_ids": finding_ids,
        "inventory_hash": inventory_hash,
        "findings": [
            {**item.model_dump(mode="json"), "finding_id": item.fingerprint} for item in page
        ],
        "cursor": cursor,
        "next_cursor": next_cursor if next_cursor < len(ordered) else None,
    }


@mcp.tool()
@_log_tool
async def get_scan_findings(
    scope: str = "full", cursor: int = 0, limit: int = 20
) -> dict[str, Any]:
    """Return a deterministic page of findings from the latest scan."""
    state = await ensure_session()
    if scope not in {"file", "diff", "full"}:
        return {"status": "error", "reason": f"invalid scope: {scope}"}
    if cursor < 0:
        return {"status": "error", "reason": "cursor must be non-negative"}
    if limit < 1 or limit > 50:
        return {"status": "error", "reason": "limit must be between 1 and 50"}
    output = _scan_findings_page(state, scope=scope, cursor=cursor, limit=limit)
    if output["status"] == "ok":
        await _mark_shown(state, [item["fingerprint"] for item in output["findings"]])
    return output
