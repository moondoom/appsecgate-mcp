"""Тулы сканирования: scan_file, scan_diff, scan_project."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from appsecgate_mcp.git import GitError, git_changed_files
from appsecgate_mcp.models.finding import ScanResult
from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.output import (
    _build_diff_output,
    _build_project_report,
    _build_scan_output,
)
from appsecgate_mcp.server.session import SessionState, _resolve_inside_project
from appsecgate_mcp.server.tools.common import ensure_session

logger = logging.getLogger(__name__)


async def _mark_shown(state: SessionState, fingerprints: list[str]) -> None:
    """K3: находки реально показаны агенту (ADR-0005 §2.3); журнал не критичен."""
    if not fingerprints or state.shown_store is None:
        return
    try:
        await state.shown_store.mark_shown(fingerprints)
    except Exception:
        logger.warning("mark_shown failed for %s fingerprint(s)", len(fingerprints))


@mcp.tool()
@_log_tool
async def scan_file(path: str) -> dict[str, Any]:
    """Scan a single file and return normalized findings.

    path — path to the file (absolute or relative to the project root).
    """
    state = await ensure_session()
    try:
        resolved = _resolve_inside_project(path, state.project_path)
    except ValueError as exc:
        return {"error": str(exc), "findings": [], "summary": {"total": 0}}
    if not resolved.is_file():
        return {"error": f"file not found: {path}", "findings": [], "summary": {"total": 0}}
    rel = str(resolved.relative_to(Path(state.project_path).resolve()))
    result = await state.coordinator.scan([rel], mode="file")
    state.register(result)
    output = await _build_scan_output(state, result)
    # K3: весь ответ scan_file попадает агенту → mark_shown.
    await _mark_shown(state, [f.fingerprint for f in result.findings])
    return output


@mcp.tool()
@_log_tool
async def scan_diff() -> dict[str, Any]:
    """Scan staged + unstaged + untracked changes in the current git repository."""
    state = await ensure_session()
    try:
        files = await git_changed_files(state.project_path)
    except GitError as exc:
        return {"error": f"git error: {exc}", "findings": [], "summary": {"total": 0}}
    if not files:
        empty = ScanResult()
        empty.meta.mode = "diff"
        empty.meta.scanned_files = []
        return await _build_diff_output(state, empty)
    result = await state.coordinator.scan(files, mode="diff")
    state.register(result)
    output = await _build_diff_output(state, result)
    # K3: в ответ scan_diff вошли top-20 → mark_shown по ним.
    await _mark_shown(state, [item["finding_id"] for item in output["top_findings"]])
    return output


@mcp.tool()
@_log_tool
async def scan_project() -> dict[str, Any]:
    """Full reconciliation: scan the whole project and return the §2.5 report.

    No arguments (ADR-0005 §2.5, breaking change): scans the entire project,
    persists all findings (positive + global negative-merge by current branch)
    and returns counts + TOP-10 + requires_confirmation + suggested_action.
    """
    state = await ensure_session()
    result = await state.coordinator.scan(["."], mode="project")
    state.register(result)
    report = await _build_project_report(state, result)
    # K3: в ответ scan_project вошли TOP-10 → mark_shown по ним.
    await _mark_shown(state, [item["finding_id"] for item in report["top_findings"]])
    return report
