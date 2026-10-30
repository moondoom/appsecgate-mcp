"""Тулы контекста: get_fix_context, get_fix_context_batch."""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.tools.common import _BATCH_LIMIT, ensure_session


@mcp.tool()
@_log_tool
async def get_fix_context(finding_id: str) -> dict[str, Any]:
    """Return the ContextPack for a finding (finding + code window + rule doc)."""
    state = await ensure_session()
    if state.context_builder is None:
        return {"status": "error", "reason": "session not initialized"}
    pack = await state.context_builder.build(finding_id)
    if pack is None:
        return {
            "status": "error",
            "reason": f"finding not found or not eligible for context: {finding_id}",
        }
    return {"status": "ok", "context": pack.model_dump(mode="json")}


@mcp.tool()
@_log_tool
async def get_fix_context_batch(finding_ids: list[str]) -> dict[str, Any]:
    """Return ContextPacks for multiple findings (limit 20)."""
    state = await ensure_session()
    if len(finding_ids) > _BATCH_LIMIT:
        return {
            "status": "error",
            "reason": f"batch limit exceeded: max {_BATCH_LIMIT} findings",
            "limit": _BATCH_LIMIT,
        }
    if state.context_builder is None:
        return {"status": "error", "reason": "session not initialized"}
    contexts: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for finding_id in finding_ids:
        pack = await state.context_builder.build(finding_id)
        if pack is None:
            errors[finding_id] = "not found or not eligible for context"
        else:
            contexts.append(pack.model_dump(mode="json"))
    return {"status": "ok", "contexts": contexts, "errors": errors, "count": len(contexts)}
