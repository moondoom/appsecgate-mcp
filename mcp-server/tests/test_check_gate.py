"""Контракт MCP-тула check_gate (ADR-0009 §3)."""

from __future__ import annotations

from datetime import datetime

import pytest

from appsecgate_mcp.config.models import Config
from appsecgate_mcp.git import GitError
from appsecgate_mcp.models.finding import Category, Finding, ScanResult, Severity
from appsecgate_mcp.orchestration.gate import GateDecision, GateReason, GateSummary
from appsecgate_mcp.orchestration.shown_source import ShownRecord
from appsecgate_mcp.server.session import SessionState
from appsecgate_mcp.server.tools import gate as gate_tool


def _finding(severity: Severity, fingerprint: str) -> Finding:
    return Finding(
        fingerprint=fingerprint,
        rule_id="rule",
        severity=severity,
        file_path="a.py",
        scanner="semgrep",
        category=Category.SAST,
    )


def _result(mode: str, *findings: Finding) -> ScanResult:
    result = ScanResult(findings=list(findings))
    result.meta.mode = mode
    return result


class _ShownStore:
    def __init__(self, *records: ShownRecord) -> None:
        self._records = {record.fingerprint: record for record in records}

    async def find(self, fingerprint: str) -> dict | None:
        record = self._records.get(fingerprint)
        if record is None:
            return None
        return {"status": record.status, "last_seen_branch": record.last_seen_branch}


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch) -> SessionState:
    session = SessionState()
    session.config = Config()
    session.shown_store = _ShownStore()
    monkeypatch.setattr(gate_tool, "ensure_session", _ensure(session))
    monkeypatch.setattr(gate_tool, "git_current_branch", _async_value("feature/x"))
    monkeypatch.setattr(gate_tool, "git_current_commit", _async_value("abc123"))
    return session


def _ensure(session: SessionState):
    async def ensure() -> SessionState:
        return session

    return ensure


def _async_value(value: str):
    async def get_value(_project: str) -> str:
        return value

    return get_value


async def test_empty_scope_proceeds_with_metadata(state: SessionState):
    response = await gate_tool.check_gate()

    assert response["should_fail"] is False
    assert response["by_reason"] == {}
    assert response["blocked_fps"] == []
    assert response["warned_fps"] == []
    assert response["recommended_action"] == "proceed"
    assert response["meta"]["scope"] == "diff"
    assert response["meta"]["policy"] == "block"
    assert response["meta"]["source"] == "local"
    assert response["meta"]["branch"] == "feature/x"
    assert response["meta"]["commit"] == "abc123"
    datetime.fromisoformat(response["meta"]["generated_at"])


async def test_check_gate_uses_latest_matching_scope(state: SessionState):
    state.register(_result("diff", _finding(Severity.CRITICAL, "old")))
    state.register(_result("diff", _finding(Severity.LOW, "new")))
    state.register(_result("project", _finding(Severity.CRITICAL, "full")))

    response = await gate_tool.check_gate(scope="diff")

    assert response["should_fail"] is False
    assert response["by_reason"] == {"ci_new": 1}
    assert response["warned_fps"] == ["new"]


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ("block", "fix_blocked"),
        ("fix", "fix_blocked"),
        ("warn", "report_only"),
        ("escalate", "escalate"),
    ],
)
async def test_recommended_action_for_blocked(state: SessionState, policy: str, expected: str):
    state.register(_result("diff", _finding(Severity.CRITICAL, "critical")))

    response = await gate_tool.check_gate(policy=policy)

    assert response["should_fail"] is True
    assert response["blocked_fps"] == ["critical"]
    assert response["by_reason"] == {"ci_severity": 1}
    assert response["recommended_action"] == expected


async def test_recommends_verifying_potentially_fixed(state: SessionState):
    state.config.gates.ci.potentially_fixed_on_block_severity = "warn"
    state.shown_store = _ShownStore(ShownRecord(fingerprint="pf", status="POTENTIALLY_FIXED"))
    state.register(_result("full", _finding(Severity.HIGH, "pf")))

    response = await gate_tool.check_gate(scope="full", policy="block")

    assert response["should_fail"] is False
    assert response["warned_fps"] == ["pf"]
    assert response["by_reason"] == {"unconfirmed_fix_critical": 1}
    assert response["recommended_action"] == "verify_fix_batch"


async def test_git_errors_become_unknown_and_warnings(
    state: SessionState, monkeypatch: pytest.MonkeyPatch
):
    async def fail(_project: str) -> str:
        raise GitError("not a repository")

    monkeypatch.setattr(gate_tool, "git_current_branch", fail)
    monkeypatch.setattr(gate_tool, "git_current_commit", fail)

    response = await gate_tool.check_gate()

    assert response["meta"]["branch"] == "<unknown>"
    assert response["meta"]["commit"] == "<unknown>"
    assert len(response["meta"]["warnings"]) == 2


@pytest.mark.parametrize(
    ("policy", "has_critical_fix", "expected"),
    [
        ("warn", True, "report_only"),
        ("escalate", True, "escalate"),
        ("block", True, "fix_blocked"),
        ("block", False, "proceed"),
        ("block", False, "verify_fix_batch"),
    ],
)
def test_recommended_action_precedence(policy: str, has_critical_fix: bool, expected: str):
    summary = GateSummary(mode="ci")
    if has_critical_fix:
        summary.blocked.append(GateDecision("fp", "block", GateReason.CI_SEVERITY))
    elif expected == "verify_fix_batch":
        summary.warned.append(GateDecision("fp", "warn", GateReason.UNCONFIRMED_FIX_CRITICAL))

    assert gate_tool._recommended_action(summary, policy) == expected


async def test_invalid_scope_is_rejected_by_mcp():
    with pytest.raises(Exception, match="scope"):
        await gate_tool.mcp.call_tool("check_gate", {"scope": "invalid"})
