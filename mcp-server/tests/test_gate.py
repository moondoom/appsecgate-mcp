"""Тесты GateEngine: локальный warn-only, CI block по severity и unresolved_local."""

from __future__ import annotations

import pytest

from appsecgate_mcp.config.models import Config
from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.orchestration.gate import GateEngine
from appsecgate_mcp.orchestration.shown_source import MasterShownSource, ShownRecord


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


def make_shown_source(*records: ShownRecord) -> MasterShownSource:
    return MasterShownSource(records=list(records))


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


# --- CI с snapshot-источником (ADR-0003 §5.2/§5.3) ---------------------------


@pytest.mark.asyncio
async def test_ci_blocks_unresolved_local_from_snapshot():
    source = make_shown_source(ShownRecord(fingerprint="fp-seen"))
    engine = GateEngine(Config(), shown_store=source)
    d = await engine.evaluate(make_finding(Severity.LOW, "fp-seen"), mode="ci")
    assert d.action == "block"
    assert d.reason == "unresolved_local"


@pytest.mark.asyncio
async def test_ci_fixed_clears_unresolved_local():
    source = make_shown_source(ShownRecord(fingerprint="fp-seen", verified_status="fixed"))
    engine = GateEngine(Config(), shown_store=source)
    d = await engine.evaluate(make_finding(Severity.LOW, "fp-seen"), mode="ci")
    assert d.action != "block"


@pytest.mark.asyncio
async def test_ci_ci_scope_clears_unresolved_local():
    source = make_shown_source(ShownRecord(fingerprint="fp-seen", suppression_scope="ci"))
    engine = GateEngine(Config(), shown_store=source)
    d = await engine.evaluate(make_finding(Severity.LOW, "fp-seen"), mode="ci")
    assert d.action != "block"


@pytest.mark.asyncio
async def test_ci_global_scope_clears_unresolved_local():
    source = make_shown_source(ShownRecord(fingerprint="fp-seen", suppression_scope="global"))
    engine = GateEngine(Config(), shown_store=source)
    d = await engine.evaluate(make_finding(Severity.LOW, "fp-seen"), mode="ci")
    assert d.action != "block"


@pytest.mark.asyncio
async def test_ci_local_scope_does_not_clear_unresolved_local():
    """Двойной контур: local-подавление CI-блок не снимает (ADR-0003 §5.2)."""
    source = make_shown_source(ShownRecord(fingerprint="fp-seen", suppression_scope="local"))
    engine = GateEngine(Config(), shown_store=source)
    d = await engine.evaluate(make_finding(Severity.LOW, "fp-seen"), mode="ci")
    assert d.action == "block"
    assert d.reason == "unresolved_local"


@pytest.mark.asyncio
async def test_ci_wont_fix_other_branch_blocks():
    """§2.3: WONT_FIX без ветки (<unknown>) → block wont_fix_other_branch."""
    source = make_shown_source(ShownRecord(fingerprint="fp-seen", verified_status="wont_fix"))
    engine = GateEngine(Config(), shown_store=source)
    d = await engine.evaluate(make_finding(Severity.LOW, "fp-seen"), mode="ci")
    assert d.action == "block"
    assert d.reason == "wont_fix_other_branch"


@pytest.mark.asyncio
async def test_ci_not_fixed_blocks_unresolved_local():
    source = make_shown_source(ShownRecord(fingerprint="fp-seen", verified_status="not_fixed"))
    engine = GateEngine(Config(), shown_store=source)
    d = await engine.evaluate(make_finding(Severity.LOW, "fp-seen"), mode="ci")
    assert d.action == "block"
    assert d.reason == "unresolved_local"


@pytest.mark.asyncio
async def test_ci_not_shown_is_not_blocked():
    """§2.3, ряд 14: нет записи → new_finding_action (default warn, reason ci_new)."""
    source = make_shown_source(ShownRecord(fingerprint="other"))
    engine = GateEngine(Config(), shown_store=source)
    d = await engine.evaluate(make_finding(Severity.LOW, "fp-seen"), mode="ci")
    assert d.action != "block"
    assert d.reason == "ci_new"
