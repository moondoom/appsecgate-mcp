"""Тесты GateEngine: локальный warn-only, CI block по severity и unresolved_local."""

from __future__ import annotations

import pytest

from secgate_mcp.config.models import Config
from secgate_mcp.models.finding import Category, Finding, Severity
from secgate_mcp.orchestration.gate import GateEngine


class FakeShownStore:
    def __init__(self, shown: set[str] | None = None) -> None:
        self._shown = shown or set()

    async def was_shown(self, fingerprint: str) -> bool:
        return fingerprint in self._shown


def make_finding(severity: Severity, fingerprint: str = "fp") -> Finding:
    return Finding(
        fingerprint=fingerprint,
        rule_id="r",
        severity=severity,
        file_path="a.py",
        scanner="semgrep",
        category=Category.SAST,
    )


@pytest.mark.asyncio
async def test_local_never_blocks():
    engine = GateEngine(Config())
    for sev in Severity:
        decision = await engine.evaluate(make_finding(sev), mode="local")
        assert decision.action in ("warn", "info")


@pytest.mark.asyncio
async def test_ci_blocks_critical_and_high():
    engine = GateEngine(Config())
    d = await engine.evaluate(make_finding(Severity.CRITICAL), mode="ci")
    assert d.action == "block"
    d = await engine.evaluate(make_finding(Severity.HIGH), mode="ci")
    assert d.action == "block"


@pytest.mark.asyncio
async def test_ci_blocks_unresolved_local():
    store = FakeShownStore(shown={"fp-seen"})
    engine = GateEngine(Config(), shown_store=store)
    # LOW сам по себе не блокируется по severity, но был показан локально.
    d = await engine.evaluate(make_finding(Severity.LOW, "fp-seen"), mode="ci")
    assert d.action == "block"
    assert d.reason == "unresolved_local"


@pytest.mark.asyncio
async def test_summary_counts():
    store = FakeShownStore(shown={"x"})
    engine = GateEngine(Config(), shown_store=store)
    findings = [make_finding(Severity.CRITICAL, "a"), make_finding(Severity.LOW, "x")]
    summary = await engine.evaluate_all(findings, mode="ci")
    assert summary.block_count == 2
    assert summary.should_fail is True
