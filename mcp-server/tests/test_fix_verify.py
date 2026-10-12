"""Тесты этапа 2 (верификация): fix_attempts, verify_fix, verify_fix_batch и views."""

from __future__ import annotations

from pathlib import Path

from appsecgate_mcp import server
from appsecgate_mcp.models.finding import Category, Finding, ScanResult, Severity
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.query import init_views, run_query
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
    def __init__(self) -> None:
        self.scan_calls: dict[str, int] = {}

    async def scan(self, files, mode="file", *, persist=True) -> ScanResult:
        for f in files:
            self.scan_calls[f] = self.scan_calls.get(f, 0) + 1
        return ScanResult()


class _StubState:
    def __init__(self, shown, attempts, db) -> None:
        self.shown_store = shown
        self.fix_attempts_store = attempts
        self.project_id = "pid-1"
        self.session_id = "sess-1"
        self.coordinator = _StubCoordinator()


async def test_verify_fix_batch_rescans_file_once(tmp_path, monkeypatch):
    db, _path, shown, attempts = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    await shown.record_shown(_finding("fp-2", file_path="b.py"), logical_id="lid-2")
    st = _StubState(shown, attempts, db)
    st.project_path = str(tmp_path)

    async def ensure(project_path=None):
        return st

    monkeypatch.setattr(server, "_ensure_session", ensure)

    out = await server.verify_fix_batch(
        [
            {"finding_id": "fp-1", "status": "fixed"},
            {"finding_id": "fp-2", "status": "fixed"},
        ]
    )
    assert out["status"] == "ok"
    assert st.coordinator.scan_calls == {"a.py": 1, "b.py": 1}
    assert out["summary"] == {"fixed": 2}
    db.close()


async def test_verify_fix_batch_same_file_single_rescan(tmp_path, monkeypatch):
    db, _path, shown, attempts = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    await shown.record_shown(_finding("fp-1b"), logical_id="lid-1b")
    st = _StubState(shown, attempts, db)
    st.project_path = str(tmp_path)

    async def ensure(project_path=None):
        return st

    monkeypatch.setattr(server, "_ensure_session", ensure)

    out = await server.verify_fix_batch(
        [
            {"finding_id": "fp-1", "status": "fixed"},
            {"finding_id": "fp-1b", "status": "fixed"},
        ]
    )
    assert out["status"] == "ok"
    assert st.coordinator.scan_calls == {"a.py": 1}
    db.close()


async def test_verify_fix_batch_limit(tmp_path, monkeypatch):
    db, _path, shown, attempts = _setup(tmp_path)
    st = _StubState(shown, attempts, db)
    st.project_path = str(tmp_path)

    async def ensure(project_path=None):
        return st

    monkeypatch.setattr(server, "_ensure_session", ensure)

    out = await server.verify_fix_batch(
        [{"finding_id": f"fp-{i}", "status": "fixed"} for i in range(21)]
    )
    assert out["status"] == "error"
    assert "20" in out["reason"]
    db.close()


async def test_verify_fix_wont_fix_records_attempt(tmp_path, monkeypatch):
    db, _path, shown, attempts = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    st = _StubState(shown, attempts, db)
    st.project_path = str(tmp_path)

    async def ensure(project_path=None):
        return st

    monkeypatch.setattr(server, "_ensure_session", ensure)

    out = await server.verify_fix("fp-1", "wont_fix", note="accepted risk")
    assert out["status"] == "ok"
    assert out["verified_status"] == "wont_fix"
    assert st.coordinator.scan_calls == {}
    attempts_list = await attempts.list_for("pid-1", "fp-1")
    assert len(attempts_list) == 1
    assert attempts_list[0]["verified_status"] == "WONT_FIX"
    assert attempts_list[0]["note"] == "accepted risk"
    row = await shown.find("fp-1")
    assert row["status"] == "WONT_FIX"
    db.close()


async def test_verify_fix_invalid_status(tmp_path, monkeypatch):
    db, _path, shown, attempts = _setup(tmp_path)
    st = _StubState(shown, attempts, db)
    st.project_path = str(tmp_path)

    async def ensure(project_path=None):
        return st

    monkeypatch.setattr(server, "_ensure_session", ensure)

    out = await server.verify_fix("fp-1", "false_positive")
    assert out["status"] == "error"
    assert "invalid status" in out["reason"]
    db.close()


async def test_verify_fix_unknown_finding(tmp_path, monkeypatch):
    db, _path, shown, attempts = _setup(tmp_path)
    st = _StubState(shown, attempts, db)
    st.project_path = str(tmp_path)

    async def ensure(project_path=None):
        return st

    monkeypatch.setattr(server, "_ensure_session", ensure)

    out = await server.verify_fix("nope", "fixed")
    assert out["status"] == "error"
    assert "finding not found" in out["reason"]
    db.close()


async def test_v_verification_coverage(tmp_path):
    db, path, shown, attempts = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    await shown.record_shown(_finding("fp-2"), logical_id="lid-2")
    await attempts.record(
        project_id="pid-1",
        logical_id="lid-1",
        fingerprint="fp-1",
        rule_id="test.rule",
        file_path="a.py",
        reported_status="fixed",
        verified_status="fixed",
        note="",
        session_id="sess-1",
    )
    result = run_query(path, "SELECT * FROM v_verification_coverage", None, "pid-1")
    assert result["row_count"] == 1
    row = result["rows"][0]
    assert row["total_findings"] == 2
    assert row["attempted_findings"] == 1
    assert row["coverage_pct"] == 50.0
    db.close()


async def test_v_attempts_view(tmp_path):
    db, path, shown, attempts = _setup(tmp_path)
    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    await attempts.record(
        project_id="pid-1",
        logical_id="lid-1",
        fingerprint="fp-1",
        rule_id="test.rule",
        file_path="a.py",
        reported_status="fixed",
        verified_status="fixed",
        note="done",
        session_id="sess-1",
    )
    result = run_query(path, "SELECT * FROM v_attempts", None, "pid-1")
    assert result["row_count"] == 1
    assert result["rows"][0]["logical_id"] == "lid-1"
    assert result["rows"][0]["verified_status"] == "fixed"
    db.close()
