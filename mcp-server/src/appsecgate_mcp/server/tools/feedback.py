"""Тулы обратной связи: submit_feedback, suppress_finding."""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.models.finding import Suppression
from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.tools.common import ensure_session


@mcp.tool()
@_log_tool
async def submit_feedback(finding_id: str, type: str, reason: str = "") -> dict[str, Any]:
    """Submit feedback on a finding.

    type: FALSE_POSITIVE | CONFIRMED | WONT_FIX.
    """
    state = await ensure_session()
    try:
        feedback_id = await state.feedback_store.save(finding_id, type, reason)
    except ValueError as exc:
        return {"status": "error", "reason": str(exc)}
    return {"status": "recorded", "finding_id": finding_id, "feedback_id": feedback_id}


@mcp.tool()
@_log_tool
async def suppress_finding(
    finding_id: str,
    reason: str,
    expires_at: str | None = None,
    action: str = "suppress",
) -> dict[str, Any]:
    """Create or remove a local suppression (does not affect CI gate in Phase 1).

    ``action``: ``suppress`` (default) | ``unsuppress``. ``unsuppress`` снимает
    suppression/WONT_FIX (ADR-0006 §1.4, эмитент ``unsuppressed``): находка
    возвращается в ``SHOWN``, suppression-запись удаляется.
    """
    state = await ensure_session()
    normalized = action.strip().lower()
    if normalized not in ("suppress", "unsuppress"):
        return {
            "status": "error",
            "reason": f"invalid action '{action}': expected suppress|unsuppress",
        }
    if normalized == "unsuppress":
        await state.suppression_store.delete(finding_id)
        try:
            await state.shown_store.unsuppress(finding_id)
        except Exception:
            pass
        return {"status": "unsuppressed", "finding_id": finding_id}
    suppression = Suppression(
        fingerprint=finding_id,
        reason=reason,
        scope="local",
        expires_at=expires_at,
    )
    await state.suppression_store.create(suppression)
    try:
        await state.shown_store.mark_suppressed(finding_id, reason)
    except Exception:
        pass
    return {"status": "suppressed", "finding_id": finding_id}
