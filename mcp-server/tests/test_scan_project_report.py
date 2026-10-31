"""PR-C: контракт scan_project (ADR-0005 §2.5) — no-args, отчёт, mark_shown, лимит 25.

- ``scan_project()`` без аргументов (Q4, breaking change).
- Новый формат §2.5: counts (без ``confirmed_fixed``, К17), TOP-10,
  ``requires_confirmation`` ≤ 25 (К18), ``suggested_action`` (К19),
  ``meta.branch``/``meta.commit``.
- ``mark_shown()`` (К3) отдельно от positive-merge (``*_seen_*``).
- Глобальный negative-merge по текущей ветке для scan_project (§2.1).
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

from appsecgate_mcp import server
from appsecgate_mcp.config.models import Config, SuppressRuleConfig
from appsecgate_mcp.models.finding import (
    Category,
    Finding,
    ReconcileReport,
    ScanResult,
    Severity,
    Suppression,
)
from appsecgate_mcp.normalization.fingerprint import FingerprintGenerator
from appsecgate_mcp.orchestration import coordinator as coordinator_mod
from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.registry import ScannerRegistry
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores import (
    FindingIdentityStore,
    ShownFindingsStore,
    SuppressionStore,
)


def _finding(
    fp: str,
    *,
    file_path: str = "a.py",
    severity: Severity = Severity.HIGH,
    rule_id: str = "test.rule",
) -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id=rule_id,
        severity=severity,
        file_path=file_path,
        line_start=3,
        line_end=4,
        message="weak md5",
        scanner="semgrep",
        category=Category.SAST,
        snippet="hashlib.md5(...)",
    )


def _setup(tmp_path: Path) -> tuple[Database, ShownFindingsStore]:
    db = Database(tmp_path / "shown.db")
    db.connect()
    FindingIdentityStore(db).init_schema()
    shown = ShownFindingsStore(db, "p1")
    shown.init_schema()
    return db, shown


class _FakeScanner(BaseScanner):
    name = "fake"

    def __init__(self, findings, **kw):
        super().__init__(**kw)
        self._findings = findings

    async def is_available(self) -> bool:
        return True

    async def scan(self, files, mode):
        return list(self._findings)


def _rf(rule_id: str, file_path: str, snippet: str = "x = 1") -> RawFinding:
    return RawFinding(
        rule_id=rule_id,
        raw_severity="high",
        file_path=file_path,
        scanner="fake",
        snippet=snippet,
        category=Category.SAST,
    )


async def _fake_git_context(project_root):
    return ("feature/x", "c1", True)


# ---------------------------------------------------------------------------
# scan_project() без аргументов (Q4)
# ---------------------------------------------------------------------------
def test_scan_project_no_args():
    sig = inspect.signature(server.scan_project)
    assert list(sig.parameters) == []

    tools = asyncio.run(server.mcp.list_tools())
    tool = next(t for t in tools if t.name == "scan_project")
    assert tool.inputSchema.get("properties", {}) == {}
    assert not tool.inputSchema.get("required")


# ---------------------------------------------------------------------------
# mark_shown отдельно от positive-merge (К3)
# ---------------------------------------------------------------------------
async def test_mark_shown_separate_from_seen(tmp_path):
    db, shown = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), branch="main", commit="c1")

    row = await shown.find("fp-1")
    assert row["first_shown_at"] is None
    assert row["show_count"] == 0
    assert row["last_seen_at"] is not None  # *_seen_* заполнен positive-merge

    await shown.mark_shown(["fp-1"])
    row = await shown.find("fp-1")
    assert row["first_shown_at"] is not None
    assert row["last_shown_at"] is not None
    assert row["show_count"] == 1

    first = row["first_shown_at"]
    await shown.mark_shown(["fp-1"])
    row = await shown.find("fp-1")
    assert row["first_shown_at"] == first  # COALESCE: только первый показ
    assert row["show_count"] == 2

    await shown.mark_shown(["missing-fp"])  # no-op, без исключения
    db.close()


async def test_mark_shown_helper(tmp_path):
    from appsecgate_mcp.server.tools.scan import _mark_shown

    db, shown = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), branch="main")
    state = server.SessionState()
    state.shown_store = shown
    await _mark_shown(state, ["fp-1"])
    assert (await shown.find("fp-1"))["show_count"] == 1


# ---------------------------------------------------------------------------
# requires_confirmation: лимит 25 + сортировка (К18)
# ---------------------------------------------------------------------------
async def test_requires_confirmation_limit_and_order(tmp_path, monkeypatch):
    from appsecgate_mcp.storage import stores as stores_mod

    counter = {"n": 0}

    def fake_now():
        counter["n"] += 1
        return f"2026-10-31T00:00:{counter['n']:02d}+00:00"

    monkeypatch.setattr(stores_mod, "_now_iso", fake_now)
    db, shown = _setup(tmp_path)

    severities = ["critical"] * 6 + ["high"] * 6 + ["medium"] * 6 + ["low"] * 6 + ["info"] * 6
    for i, sev in enumerate(reversed(severities)):
        f = _finding(f"fp-{i:02d}", severity=Severity(sev))
        await shown.record_shown(f, branch="feature/x", commit="c0")
        await shown.mark_missing([(f.fingerprint, "POTENTIALLY_FIXED", 1)])

    ids, total, truncated = await shown.list_potentially_fixed("feature/x", limit=25)
    assert total == 30
    assert truncated is True
    assert len(ids) == 25
    # severity desc → critical первыми; внутри — last_seen_at desc.
    assert ids[:6] == [f"fp-{i:02d}" for i in range(29, 23, -1)]
    db.close()


async def test_requires_confirmation_ignores_other_branch(tmp_path, monkeypatch):
    from appsecgate_mcp.storage import stores as stores_mod

    monkeypatch.setattr(
        stores_mod,
        "_now_iso",
        lambda: "2026-10-31T00:00:00+00:00",
    )
    db, shown = _setup(tmp_path)
    await shown.record_shown(_finding("fp-main"), branch="main")
    await shown.record_shown(_finding("fp-feat"), branch="feature/x")
    await shown.mark_missing(
        [("fp-main", "POTENTIALLY_FIXED", 1), ("fp-feat", "POTENTIALLY_FIXED", 1)]
    )

    ids, total, truncated = await shown.list_potentially_fixed("feature/x")
    assert ids == ["fp-feat"]
    assert total == 1
    assert truncated is False
    db.close()


# ---------------------------------------------------------------------------
# Глобальный negative-merge scan_project (§2.1): по всему проекту/ветке
# ---------------------------------------------------------------------------
async def test_negative_merge_global_project_mode(tmp_path, monkeypatch, default_config):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    db, shown = _setup(tmp_path)
    await shown.record_shown(_finding("fp-other", file_path="other.py"), branch="feature/x")

    monkeypatch.setattr(coordinator_mod, "git_context", _fake_git_context)
    registry = ScannerRegistry()
    registry.register(_FakeScanner([]))
    coord = ScanCoordinator(
        default_config,
        registry,
        shown_store=shown,
        project_root=str(tmp_path),
        project_id="p1",
    )

    result = await coord.scan(["."], mode="project")
    row = await shown.find("fp-other")
    assert row is not None and row["status"] == "POTENTIALLY_FIXED"
    assert result.reconcile is not None
    assert result.reconcile.counts["potentially_fixed"] == 1
    assert result.reconcile.potentially_fixed_fingerprints == ["fp-other"]
    assert result.reconcile.branch == "feature/x"
    db.close()


# ---------------------------------------------------------------------------
# counts: new / reaffirmed / reopened / suppressed
# ---------------------------------------------------------------------------
async def test_counts_new_reaffirmed_reopened(tmp_path, monkeypatch, default_config):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    db, shown = _setup(tmp_path)
    monkeypatch.setattr(coordinator_mod, "git_context", _fake_git_context)
    registry = ScannerRegistry()
    registry.register(_FakeScanner([_rf("test.rule", "a.py")]))
    coord = ScanCoordinator(
        default_config,
        registry,
        shown_store=shown,
        project_root=str(tmp_path),
        project_id="p1",
    )

    r1 = await coord.scan(["."], mode="project")
    assert r1.total == 1
    assert r1.reconcile.counts["new"] == 1
    assert r1.reconcile.counts["reaffirmed"] == 0
    assert r1.reconcile.counts["reopened"] == 0
    fp = r1.findings[0].fingerprint

    r2 = await coord.scan(["."], mode="project")
    assert r2.reconcile.counts["new"] == 0
    assert r2.reconcile.counts["reaffirmed"] == 1

    await shown.set_status(fp, "FIXED", confirmed_by="verify_fix")
    r3 = await coord.scan(["."], mode="project")
    assert r3.reconcile.counts["reopened"] == 1
    assert (await shown.find(fp))["status"] == "REOPENED"
    db.close()


async def test_counts_suppressed(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    db, shown = _setup(tmp_path)
    sup = SuppressionStore(db, "p1")
    sup.init_schema()

    fp_store = FingerprintGenerator().generate_for("ok.rule", "ok.py", "x = 1")
    await sup.create(Suppression(fingerprint=fp_store, reason="known"))
    config = Config(suppress=[SuppressRuleConfig(rule="noise.rule")])

    monkeypatch.setattr(coordinator_mod, "git_context", _fake_git_context)
    registry = ScannerRegistry()
    registry.register(
        _FakeScanner(
            [
                _rf("noise.rule", "noise.py"),
                _rf("ok.rule", "ok.py"),
                _rf("clean.rule", "clean.py"),
            ]
        )
    )
    coord = ScanCoordinator(
        config,
        registry,
        shown_store=shown,
        suppression_store=sup,
        project_root=str(tmp_path),
        project_id="p1",
    )

    result = await coord.scan(["."], mode="project")
    assert result.reconcile.counts["suppressed"] == 2  # config + store фильтры (К6)
    assert result.total == 1  # выжил только clean.rule
    db.close()


# ---------------------------------------------------------------------------
# Формат отчёта §2.5 (_build_project_report)
# ---------------------------------------------------------------------------
async def test_build_project_report_format():
    findings = [
        Finding(
            fingerprint=f"fp-{i}",
            rule_id="opengrep.rb.gems.security.rule-omni",
            severity=Severity.HIGH if i < 2 else Severity.LOW,
            file_path="a.rb",
            scanner="semgrep",
            category=Category.SAST,
        )
        for i in range(15)
    ]
    result = ScanResult(findings=findings)
    result.meta.mode = "project"
    result.meta.scanned_files = ["."]
    result.reconcile = ReconcileReport(
        counts={"new": 3, "reaffirmed": 11, "reopened": 0, "potentially_fixed": 1, "suppressed": 0},
        potentially_fixed_fingerprints=["fp-1"],
        potentially_fixed_total=1,
        requires_confirmation_truncated=False,
        branch="feature/x",
        commit="abc1234",
    )

    state = server.SessionState()
    state.project_id = "pid-1"
    out = await server._build_project_report(state, result)

    assert out["status"] == "ok"
    assert out["counts"] == {
        "new": 3,
        "reaffirmed": 11,
        "reopened": 0,
        "potentially_fixed": 1,
        "suppressed": 0,
    }
    assert "confirmed_fixed" not in out["counts"]  # К17
    assert len(out["top_findings"]) == 10
    assert out["top_findings"][0]["finding_id"] == "fp-0"
    assert out["top_findings"][0]["rule_id"] == "opengrep.rb.gems.security.rule-omni"
    assert out["top_findings"][0]["rule"] == "rule-omni"  # T15
    assert out["requires_confirmation"] == {
        "finding_ids": ["fp-1"],
        "total_potentially_fixed": 1,
        "truncated": False,
    }
    assert out["suggested_action"] == "run verify_fix_batch on requires_confirmation.finding_ids"
    assert out["meta"]["branch"] == "feature/x"
    assert out["meta"]["commit"] == "abc1234"
    assert out["meta"]["mode"] == "project"


async def test_build_project_report_no_requires_confirmation():
    state = server.SessionState()
    state.project_id = "pid-1"
    result = ScanResult()
    result.reconcile = ReconcileReport(
        counts={"new": 0, "reaffirmed": 0, "reopened": 0, "potentially_fixed": 0, "suppressed": 0},
        branch="<unknown>",
    )
    out = await server._build_project_report(state, result)
    assert out["requires_confirmation"] == {"finding_ids": [], "total_potentially_fixed": 0, "truncated": False}
    assert out["suggested_action"] == "no findings require confirmation"
    assert out["top_findings"] == []
