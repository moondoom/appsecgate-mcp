"""Применение локальных и центральных suppression-фильтров к находкам."""

from __future__ import annotations

from appsecgate_mcp.models.finding import Finding


async def apply_suppression_filters(
    findings: list[Finding],
    *,
    local_store=None,
    remote_store=None,
) -> list[Finding]:
    result = findings
    if local_store is not None:
        try:
            result = await local_store.filter_active(result)
        except Exception:
            result = findings
    if remote_store is not None:
        try:
            result = await remote_store.filter_active(result)
        except Exception:
            pass
    return result
