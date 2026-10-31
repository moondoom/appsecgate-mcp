"""Маппинг verify_fix → статус shown_findings (ADR-0005 §2.9).

- reported=fixed + перескан чист → FIXED, fixed_confirmed_by='verify_fix' (§2.3).
- reported=fixed + перескан нашёл → REOPENED.
- reported=not_fixed → статус не меняется.
- wont_fix → WONT_FIX c wont_fix_at/wont_fix_reason.
"""

from __future__ import annotations

from pathlib import Path

from appsecgate_mcp import server
from appsecgate_mcp.models.finding import Category, Finding, ScanResult, Severity
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.query import init_views
from appsecgate_mcp.storage.stores import (
    FindingContextStore,
    FindingIdentityStore,
    FixAttemptsStore,
    ProjectsStore,
    ShownFindingsStore,
    SuppressionStore,
)


def _finding(fp: str, *, file_path: str = "a.py") -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="test.rule",
        severity=Severity.HIGH,
        file_path=file_path,
        line_start=1,
        line_end=1,
        message="m",
        scanner="semgrep",
        category=Category.SAST,
        snippet="hashlib.md5(...)",
    )


def _setup(tmp_path: Path) -> tuple[Database, Path, ShownFindingsStore, FixAttemptsStore]:
    db = Database(tmp_path / "shown.db")
    db.connect()
    shown = ShownFindingsStore(db, "pid-1")
    shown.init_schema()
    FindingIdentityStore(db).init_schema()
    FindingContextStore(db).init_schema()
    ProjectsStore(db).init_schema()
    SuppressionStore(db).init_schema()
    attempts = FixAttemptsStore(db)
    attempts.init_schema()
    init_views(db)
    return db, db.path, shown, attempts


class _StubCoordinator:
    async def scan(self, files, mode="file", *, persist=True) -> ScanResult:
        return ScanResult()


class _StubState:
    def __init__(self, shown, attempts, db) -> None:
        self.shown_store = shown
        self.fix_attempts_store = attempts
        self.project_id = "pid-1"
        self.session_id = "sess-1"
        self.coordinator = _StubCoordinator()


class _HitCoordinator(_StubCoordinator):
    """Перескан возвращает ту же находку (регрессия при reported=fixed)."""

    async def scan(self, files, mode="file", *, persist=True) -> ScanResult:
        return ScanResult(findings=[_finding("fp-1")])


async def test_verify_fix_not_fixed_maps_to_reopened(tmp_path, monkeypatch):
    """§2.9: reported=fixed + перескан нашёл → verified=not_fixed → REOPENED."""
    db, _path, shown, attempts = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    st = _StubState(shown, attempts, db)
    st.coordinator = _HitCoordinator()
    st.project_path = str(tmp_path)

    async def ensure(project_path=None):
        return st

    monkeypatch.setattr(server, "_ensure_session", ensure)
    monkeypatch.setattr(
        server, "compute_logical_id", lambda rule_id, file_path, line_start, source: "lid-1"
    )

    out = await server.verify_fix("fp-1", "fixed")
    assert out["verified_status"] == "not_fixed"
    assert (await shown.find("fp-1"))["status"] == "REOPENED"
    db.close()


async def test_verify_fix_fixed_maps_to_fixed_with_confirmed_by(tmp_path, monkeypatch):
    """§2.9/§2.3: reported=fixed + перескан чист → FIXED, fixed_confirmed_by='verify_fix'."""
    db, _path, shown, attempts = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    st = _StubState(shown, attempts, db)
    st.project_path = str(tmp_path)

    async def ensure(project_path=None):
        return st

    monkeypatch.setattr(server, "_ensure_session", ensure)

    out = await server.verify_fix("fp-1", "fixed")
    assert out["verified_status"] == "fixed"
    row = await shown.find("fp-1")
    assert row["status"] == "FIXED"
    assert row["fixed_confirmed_by"] == "verify_fix"
    assert row["fixed_at"] is not None
    db.close()


async def test_verify_fix_wont_fix_mapping(tmp_path, monkeypatch):
    """§2.9: wont_fix → WONT_FIX c wont_fix_at/wont_fix_reason."""
    db, _path, shown, attempts = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    st = _StubState(shown, attempts, db)
    st.project_path = str(tmp_path)

    async def ensure(project_path=None):
        return st

    monkeypatch.setattr(server, "_ensure_session", ensure)

    out = await server.verify_fix("fp-1", "wont_fix", note="accepted risk")
    assert out["verified_status"] == "wont_fix"
    row = await shown.find("fp-1")
    assert row["status"] == "WONT_FIX"
    assert row["wont_fix_reason"] == "accepted risk"
    assert row["wont_fix_at"] is not None
    db.close()


async def test_verify_fix_not_fixed_reported_keeps_status(tmp_path, monkeypatch):
    """§2.9: reported=not_fixed + перескан нашёл → статус не меняется."""
    db, _path, shown, attempts = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    st = _StubState(shown, attempts, db)
    st.coordinator = _HitCoordinator()
    st.project_path = str(tmp_path)

    async def ensure(project_path=None):
        return st

    monkeypatch.setattr(server, "_ensure_session", ensure)
    monkeypatch.setattr(
        server, "compute_logical_id", lambda rule_id, file_path, line_start, source: "lid-1"
    )

    out = await server.verify_fix("fp-1", "not_fixed")
    assert out["verified_status"] == "not_fixed"
    assert (await shown.find("fp-1"))["status"] == "SHOWN"
    db.close()
