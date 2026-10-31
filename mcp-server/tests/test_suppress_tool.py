"""suppress_finding(action=...) (SM-1, ADR-0006 §1.4/§2.1).

- action="suppress" (default) — прежнее поведение: suppression + SUPPRESSED.
- action="unsuppress" — снятие SUPPRESSED/WONT_FIX → SHOWN (эмитент
  ``unsuppressed``): статус, маркеры и suppression-запись очищаются.
"""

from __future__ import annotations

from pathlib import Path

from appsecgate_mcp import server
from appsecgate_mcp.models.finding import Category, Finding, Severity
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


def _finding(fp: str) -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="test.rule",
        severity=Severity.HIGH,
        file_path="a.py",
        line_start=1,
        line_end=1,
        message="m",
        scanner="semgrep",
        category=Category.SAST,
        snippet="x = 1",
    )


def _setup(tmp_path: Path) -> tuple[Database, ShownFindingsStore, SuppressionStore]:
    db = Database(tmp_path / "shown.db")
    db.connect()
    shown = ShownFindingsStore(db, "pid-1")
    shown.init_schema()
    FindingIdentityStore(db).init_schema()
    FindingContextStore(db).init_schema()
    ProjectsStore(db).init_schema()
    suppression = SuppressionStore(db, "pid-1")
    suppression.init_schema()
    FixAttemptsStore(db).init_schema()
    init_views(db)
    return db, shown, suppression


class _StubState:
    def __init__(self, shown: ShownFindingsStore, suppression: SuppressionStore) -> None:
        self.shown_store = shown
        self.suppression_store = suppression


def _stub_session(shown: ShownFindingsStore, suppression: SuppressionStore, monkeypatch) -> None:
    state = _StubState(shown, suppression)

    async def ensure(project_path=None):
        return state

    monkeypatch.setattr(server, "_ensure_session", ensure)


async def test_suppress_finding_creates_suppression(tmp_path, monkeypatch):
    db, shown, sup = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    _stub_session(shown, sup, monkeypatch)

    out = await server.suppress_finding("fp-1", "accepted risk")
    assert out["status"] == "suppressed"
    row = await shown.find("fp-1")
    assert row["status"] == "SUPPRESSED"
    assert row["suppress_reason"] == "accepted risk"
    assert await sup.get("fp-1") is not None
    db.close()


async def test_unsuppress_via_suppress_finding(tmp_path, monkeypatch):
    """§2.1: SUPPRESSED --unsuppressed--> SHOWN, suppression-запись удаляется."""
    db, shown, sup = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    _stub_session(shown, sup, monkeypatch)

    assert (await server.suppress_finding("fp-1", "accepted risk"))["status"] == "suppressed"
    assert (await shown.find("fp-1"))["status"] == "SUPPRESSED"

    out = await server.suppress_finding("fp-1", "", action="unsuppress")
    assert out["status"] == "unsuppressed"
    row = await shown.find("fp-1")
    assert row["status"] == "SHOWN"
    assert row["suppress_reason"] is None
    assert row["suppressed_at"] is None
    assert await sup.get("fp-1") is None
    db.close()


async def test_unsuppress_wont_fix_returns_to_shown(tmp_path, monkeypatch):
    """§2.1: WONT_FIX --unsuppressed--> SHOWN (маркеры wont_fix очищаются)."""
    db, shown, sup = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    await shown.set_status("fp-1", "WONT_FIX", reason="accepted risk")
    _stub_session(shown, sup, monkeypatch)
    assert (await shown.find("fp-1"))["status"] == "WONT_FIX"

    out = await server.suppress_finding("fp-1", "", action="unsuppress")
    assert out["status"] == "unsuppressed"
    row = await shown.find("fp-1")
    assert row["status"] == "SHOWN"
    assert row["wont_fix_reason"] is None
    assert row["wont_fix_at"] is None
    db.close()


async def test_suppress_finding_invalid_action(tmp_path, monkeypatch):
    db, shown, sup = _setup(tmp_path)
    _stub_session(shown, sup, monkeypatch)

    out = await server.suppress_finding("fp-1", "x", action="nope")
    assert out["status"] == "error"
    assert "invalid action" in out["reason"]
    assert await sup.get("fp-1") is None
    db.close()
