"""Итоговое advisory-решение gate для agent mode."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from appsecgate_mcp.git import GitError, git_current_branch, git_current_commit
from appsecgate_mcp.orchestration.gate import GateEngine, GateReason, GateSummary
from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.tools.common import ensure_session

GateScope = Literal["file", "diff", "full"]
GatePolicy = Literal["warn", "block", "escalate", "fix"]


def _recommended_action(summary: GateSummary, policy: GatePolicy) -> str:
    if policy == "warn":
        return "report_only"
    if policy == "escalate":
        return "escalate"
    if summary.should_fail:
        return "fix_blocked"
    if any(d.reason == GateReason.UNCONFIRMED_FIX_CRITICAL for d in summary.warned):
        return "verify_fix_batch"
    return "proceed"


@mcp.tool()
@_log_tool
async def check_gate(scope: GateScope = "diff", policy: GatePolicy = "block") -> dict[str, Any]:
    """Evaluate findings from the latest scan of the given scope.

    scope: file | diff | full. policy: warn | block | escalate | fix.
    The result is advisory: policy controls recommended_action, while should_fail
    always reflects the gate matrix. Uses local shown_findings state only.
    """
    state = await ensure_session()
    assert state.config is not None
    result = state.last_results.get(scope)
    findings = result.findings if result is not None else []

    warnings: list[str] = []
    try:
        branch = await git_current_branch(state.project_path)
    except GitError:
        branch = "<unknown>"
        warnings.append("current branch is unavailable")
    try:
        commit = await git_current_commit(state.project_path)
    except GitError:
        commit = "<unknown>"
        warnings.append("current commit is unavailable")

    engine = GateEngine(state.config, shown_store=state.shown_store, branch=branch)
    summary = await engine.evaluate_all(findings, mode="ci")
    return {
        "should_fail": summary.should_fail,
        "by_reason": summary.by_reason,
        "blocked_fps": [d.fingerprint for d in summary.blocked],
        "warned_fps": [d.fingerprint for d in summary.warned],
        "recommended_action": _recommended_action(summary, policy),
        "meta": {
            "policy": policy,
            "scope": scope,
            "source": "local",
            "branch": branch,
            "commit": commit,
            "generated_at": datetime.now(UTC).isoformat(),
            "warnings": warnings,
        },
    }
