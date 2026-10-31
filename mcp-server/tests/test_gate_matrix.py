"""Гейт-матрица ADR-0006 §2.3 (PR-D): по одному тесту на каждый ряд.

``decide`` — чистая табличная функция; для ``skip-if-same-branch`` нужна
ветка CI (``branch``). ``<unknown>`` никогда не равен CI-branch → block.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from appsecgate_mcp.config.models import CiGateConfig, Config
from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.orchestration.gate import GateEngine, decide
from appsecgate_mcp.orchestration.shown_source import (
    ShownRecord,
    ShownSnapshot,
    SnapshotShownSource,
)

UNKNOWN = "<unknown>"


def _finding(severity: Severity, fp: str = "fp") -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="r",
        severity=severity,
        file_path="a.py",
        scanner="semgrep",
        category=Category.SAST,
    )


def _record(status: str, **kw) -> ShownRecord:
    return ShownRecord(fingerprint="fp", status=status, **kw)


def _cfg(**overrides) -> CiGateConfig:
    return CiGateConfig(**overrides)


# Ряд 1: severity ∈ block_on → block ci_severity (независимо от статуса).
def test_row_severity_block_overrides_status():
    d = decide(_finding(Severity.CRITICAL), _record("SHOWN"), cfg=_cfg(), branch="main")
    assert (d.action, d.reason) == ("block", "ci_severity")


# Ряд 2: SHOWN → block unresolved_local («знал и не починил»).
def test_row_shown_blocks_unresolved():
    d = decide(_finding(Severity.LOW), _record("SHOWN"), cfg=_cfg(), branch="main")
    assert (d.action, d.reason) == ("block", "unresolved_local")


# Ряд 3: REOPENED → block reopened.
def test_row_reopened_blocks():
    d = decide(_finding(Severity.LOW), _record("REOPENED"), cfg=_cfg(), branch="main")
    assert (d.action, d.reason) == ("block", "reopened")


# Ряд 4: POTENTIALLY_FIXED + block-severity → block unconfirmed_fix_critical (default).
def test_row_pf_block_severity_blocks():
    d = decide(_finding(Severity.HIGH), _record("POTENTIALLY_FIXED"), cfg=_cfg(), branch="main")
    assert (d.action, d.reason) == ("block", "unconfirmed_fix_critical")


# Ряд 4 (конфиг): potentially_fixed_on_block_severity=warn → warn (Q2).
def test_row_pf_block_severity_warns_when_configured():
    d = decide(
        _finding(Severity.HIGH),
        _record("POTENTIALLY_FIXED"),
        cfg=_cfg(potentially_fixed_on_block_severity="warn"),
        branch="main",
    )
    assert (d.action, d.reason) == ("warn", "unconfirmed_fix_critical")


# Ряд 5: POTENTIALLY_FIXED + не-block-severity → warn unconfirmed_fix.
def test_row_pf_non_block_severity_warns():
    d = decide(_finding(Severity.LOW), _record("POTENTIALLY_FIXED"), cfg=_cfg(), branch="main")
    assert (d.action, d.reason) == ("warn", "unconfirmed_fix")


# Ряд 6: FIXED → skip.
def test_row_fixed_skips():
    d = decide(_finding(Severity.LOW), _record("FIXED"), cfg=_cfg(), branch="main")
    assert (d.action, d.reason) == ("skip", "fixed")


# Ряд 7: SUPPRESSED + scope ci/global + не истёк → skip suppressed.
def test_row_suppressed_ci_scope_skips():
    d = decide(
        _finding(Severity.LOW),
        _record("SUPPRESSED", suppression_scope="ci"),
        cfg=_cfg(),
        branch="main",
    )
    assert (d.action, d.reason) == ("skip", "suppressed")


def test_row_suppressed_global_scope_skips():
    d = decide(
        _finding(Severity.LOW),
        _record("SUPPRESSED", suppression_scope="global"),
        cfg=_cfg(),
        branch="main",
    )
    assert (d.action, d.reason) == ("skip", "suppressed")


# Ряд 7 (истёк): ci/global истёк → block unresolved_local (suppression_expired inline).
def test_row_suppressed_ci_expired_blocks():
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    d = decide(
        _finding(Severity.LOW),
        _record("SUPPRESSED", suppression_scope="ci", suppression_expires_at=past),
        cfg=_cfg(),
        branch="main",
    )
    assert (d.action, d.reason) == ("block", "unresolved_local")


# Ряд 8: SUPPRESSED + scope local → block unresolved_local (двойной контур, Q3).
def test_row_suppressed_local_blocks():
    d = decide(
        _finding(Severity.LOW),
        _record("SUPPRESSED", suppression_scope="local"),
        cfg=_cfg(),
        branch="main",
    )
    assert (d.action, d.reason) == ("block", "unresolved_local")


# Ряд 8 (конфиг): local_suppression_hides=true → skip.
def test_row_suppressed_local_hides_when_configured():
    d = decide(
        _finding(Severity.LOW),
        _record("SUPPRESSED", suppression_scope="local"),
        cfg=_cfg(local_suppression_hides=True),
        branch="main",
    )
    assert (d.action, d.reason) == ("skip", "suppressed")


# Ряд 12: WONT_FIX + своя ветка → skip wont_fix.
def test_row_wont_fix_same_branch_skips():
    d = decide(
        _finding(Severity.LOW),
        _record("WONT_FIX", last_seen_branch="feature/x"),
        cfg=_cfg(),
        branch="feature/x",
    )
    assert (d.action, d.reason) == ("skip", "wont_fix")


# Ряд 13: WONT_FIX + чужая ветка → block wont_fix_other_branch.
def test_row_wont_fix_other_branch_blocks():
    d = decide(
        _finding(Severity.LOW),
        _record("WONT_FIX", last_seen_branch="other"),
        cfg=_cfg(),
        branch="feature/x",
    )
    assert (d.action, d.reason) == ("block", "wont_fix_other_branch")


# Правило <unknown>: last_seen_branch=<unknown> никогда не равен CI-branch.
def test_row_wont_fix_unknown_branch_blocks():
    d = decide(
        _finding(Severity.LOW),
        _record("WONT_FIX", last_seen_branch=UNKNOWN),
        cfg=_cfg(),
        branch="feature/x",
    )
    assert (d.action, d.reason) == ("block", "wont_fix_other_branch")


# Ветка CI не определена (None) → консервативный block.
def test_row_wont_fix_no_ci_branch_blocks():
    d = decide(
        _finding(Severity.LOW),
        _record("WONT_FIX", last_seen_branch="feature/x"),
        cfg=_cfg(),
        branch=None,
    )
    assert (d.action, d.reason) == ("block", "wont_fix_other_branch")


# Ряд 10: wont_fix_action=skip → skip независимо от ветки.
def test_row_wont_fix_action_skip():
    d = decide(
        _finding(Severity.LOW),
        _record("WONT_FIX", last_seen_branch="other"),
        cfg=_cfg(wont_fix_action="skip"),
        branch="feature/x",
    )
    assert (d.action, d.reason) == ("skip", "wont_fix")


# Ряд 11: wont_fix_action=block → block независимо от ветки.
def test_row_wont_fix_action_block():
    d = decide(
        _finding(Severity.LOW),
        _record("WONT_FIX", last_seen_branch="feature/x"),
        cfg=_cfg(wont_fix_action="block"),
        branch="feature/x",
    )
    assert (d.action, d.reason) == ("block", "wont_fix")


# Ряд 14: нет записи → new_finding_action (default warn, reason ci_new).
def test_row_no_record_default_warns():
    d = decide(_finding(Severity.LOW), None, cfg=_cfg(), branch="main")
    assert (d.action, d.reason) == ("warn", "ci_new")


def test_row_no_record_blocks_when_configured():
    d = decide(_finding(Severity.LOW), None, cfg=_cfg(new_finding_action="block"), branch="main")
    assert (d.action, d.reason) == ("block", "ci_new")


def test_row_no_record_infos_when_configured():
    d = decide(_finding(Severity.LOW), None, cfg=_cfg(new_finding_action="info"), branch="main")
    assert (d.action, d.reason) == ("info", "ci_new")


# GateSummary: skip_count + by_reason по всем контурам.
async def test_gate_summary_by_reason_and_skip():
    source = SnapshotShownSource(
        ShownSnapshot(
            records=[
                ShownRecord(fingerprint="b", status="FIXED"),
                ShownRecord(fingerprint="c", status="WONT_FIX", last_seen_branch="feature/x"),
            ]
        )
    )
    engine = GateEngine(Config(), shown_store=source, branch="feature/x")
    findings = [
        _finding(Severity.CRITICAL, "a"),  # block ci_severity
        _finding(Severity.LOW, "b"),  # skip fixed
        _finding(Severity.LOW, "c"),  # skip wont_fix
        _finding(Severity.LOW, "d"),  # warn ci_new
    ]
    summary = await engine.evaluate_all(findings, mode="ci")
    assert summary.block_count == 1
    assert summary.skip_count == 2
    assert summary.should_fail is True
    assert summary.by_reason == {
        "ci_severity": 1,
        "fixed": 1,
        "wont_fix": 1,
        "ci_new": 1,
    }

