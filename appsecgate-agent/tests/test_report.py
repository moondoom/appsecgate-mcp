"""Форматы отчётов server-agent."""

from __future__ import annotations

import json

from appsecgate_agent.report import render_markdown, render_ndjson
from appsecgate_agent.runner import AgentResult


def _result() -> AgentResult:
    return AgentResult(
        scan={"summary": {"total": 2}},
        gate={
            "should_fail": True,
            "recommended_action": "fix_blocked",
            "blocked_fps": ["fp-b", "fp-a"],
            "warned_fps": [],
            "by_reason": {"ci_severity": 2},
            "meta": {"scope": "diff", "policy": "block"},
        },
    )


def test_markdown_contains_gate_decision_and_blocked_fps():
    output = render_markdown(_result())

    assert "Should fail: `true`" in output
    assert "Recommended action: `fix_blocked`" in output
    assert "`ci_severity`: 2" in output
    assert "- `fp-a`" in output


def test_ndjson_is_single_machine_readable_object():
    output = render_ndjson(_result())
    payload = json.loads(output)

    assert payload["type"] == "appsecgate_report"
    assert payload["scan"]["summary"]["total"] == 2
    assert payload["gate"]["blocked_fps"] == ["fp-b", "fp-a"]
    assert len(output.splitlines()) == 1
