"""Тулы сканирования: scan_file, scan_diff, scan_project."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from appsecgate_mcp.git import GitError, git_changed_files
from appsecgate_mcp.models.finding import ScanResult
from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.output import _build_announce_output, _build_scan_output
from appsecgate_mcp.server.session import _resolve_inside_project
from appsecgate_mcp.server.tools.common import ensure_session


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
    return await _build_scan_output(state, result)


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
        return await _build_announce_output(state, empty)
    result = await state.coordinator.scan(files, mode="diff")
    state.register(result)
    return await _build_announce_output(state, result)


@mcp.tool()
@_log_tool
async def scan_project(path: str = ".") -> dict[str, Any]:
    """Scan the entire project or a specific directory inside it.

    path — directory (absolute or relative to the project root).
    Defaults to the full project. Runs all scanners in ``project`` mode:
    semgrep — per file, gitleaks/trufflehog/trivy — per directory.
    """
    state = await ensure_session()
    try:
        target = _resolve_inside_project(path or ".", state.project_path)
    except ValueError as exc:
        return {"error": str(exc), "findings": [], "summary": {"total": 0}}
    if not target.exists():
        return {"error": f"path not found: {path}", "findings": [], "summary": {"total": 0}}
    if not target.is_dir():
        return {
            "error": f"not a directory: {path} (use scan_file for a single file)",
            "findings": [],
            "summary": {"total": 0},
        }

    rel = str(target.relative_to(Path(state.project_path).resolve()))
    # announce-only: сканируем без записи в shown/identity/context (§4.3, F3).
    result = await state.coordinator.scan([rel], mode="project")
    return await _build_announce_output(state, result)
