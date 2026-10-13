"""Тесты этапа 1 (хвост 1.4–1.9): ContextBuilder, get_fix_context, query_findings_db,
sql_audit_log, export_snapshot и announce-only scan_project."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from appsecgate_mcp import server
from appsecgate_mcp.models.finding import Category, Finding, ScanResult, Severity
from appsecgate_mcp.orchestration.context_builder import ContextBuilder
from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.registry import ScannerRegistry
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.query import (
    ReadOnlyQueryError,
    _finalize,
    init_views,
    run_query,
)
from appsecgate_mcp.storage.stores import (
    FindingContextStore,
    FindingIdentityStore,
    ProjectsStore,
    ShownFindingsStore,
    SqlAuditLogStore,
)


def _make_finding(fp: str, *, category=Category.SAST, line_start=3, line_end=4) -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="test.rule",
        severity=Severity.HIGH,
        file_path="app.py",
        line_start=line_start,
        line_end=line_end,
        message="weak md5",
        scanner="semgrep",
        category=category,
        snippet="hashlib.md5(...)",
    )


def _setup_db(tmp_path: Path) -> tuple[Database, Path]:
    db = Database(tmp_path / "shown.db")
    db.connect()
    ShownFindingsStore(db, "pid-1").init_schema()
    FindingIdentityStore(db).init_schema()
    FindingContextStore(db).init_schema()
    ProjectsStore(db).init_schema()
    SqlAuditLogStore(db).init_schema()
    init_views(db)
    return db, db.path


# ---------------------------------------------------------------------------
# ContextBuilder
# ---------------------------------------------------------------------------
async def test_context_builder_builds_pack(tmp_path):
    (tmp_path / "app.py").write_text(
        "import hashlib\n\ndef go():\n    hashlib.md5(b'x')\n", encoding="utf-8"
    )
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = FindingContextStore(db)
    store.init_schema()
    await store.upsert("pid-1", "logical-1", _make_finding("fp-1"))

    builder = ContextBuilder(
        store, project_root=str(tmp_path), project_id="pid-1", project_alias="app"
    )
    pack = await builder.build("fp-1")
    assert pack is not None
    assert pack.project.project_id == "pid-1"
    assert pack.project.project_alias == "app"
    assert pack.finding.fingerprint == "fp-1"
    assert pack.window is not None
    assert pack.window.finding_lines == (3, 4)
    assert pack.rule.rule_id == "test.rule"
    assert pack.prompt_version == "v1"
    db.close()


async def test_context_builder_license_returns_none(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = FindingContextStore(db)
    store.init_schema()
    await store.upsert("pid-1", "logical-1", _make_finding("fp-lic", category=Category.LICENSE))

    builder = ContextBuilder(store, project_root=str(tmp_path), project_id="pid-1")
    assert await builder.build("fp-lic") is None
    db.close()


async def test_context_builder_missing_finding_returns_none(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = FindingContextStore(db)
    store.init_schema()
    builder = ContextBuilder(store, project_root=str(tmp_path), project_id="pid-1")
    assert await builder.build("does-not-exist") is None
    db.close()


async def test_context_builder_sca_extracts_package(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = FindingContextStore(db)
    store.init_schema()
    finding = _make_finding("fp-sca", category=Category.SCA, line_start=1, line_end=1)
    finding.metadata = {"package": "requests", "installed_version": "2.0", "fixed_version": "2.1"}
    await store.upsert("pid-1", "logical-1", finding)

    builder = ContextBuilder(store, project_root=str(tmp_path), project_id="pid-1")
    pack = await builder.build("fp-sca")
    assert pack is not None and pack.sca is not None
    assert pack.sca.package == "requests"
    assert pack.sca.installed_version == "2.0"
    assert pack.sca.fixed_version == "2.1"
    db.close()


# ---------------------------------------------------------------------------
# Redaction до записи (инвариант №4)
# ---------------------------------------------------------------------------
async def test_context_store_redacts_secret_snippet(tmp_path):
    from appsecgate_mcp.normalization.redactor import Redactor

    db = Database(tmp_path / "shown.db")
    db.connect()
    store = FindingContextStore(db)
    store.init_schema()
    finding = _make_finding("fp-secret", category=Category.SECRET)
    finding.snippet = "AKIA1234567890ABCDEF"
    redacted, _ = Redactor().redact_finding(finding)
    await store.upsert("pid-1", "logical-1", redacted)
    row = await store.get("pid-1", "fp-secret")
    assert row is not None
    assert "AKIA" not in row["snippet"]
    assert "AKIA" not in json.dumps(row["metadata_json"])
    db.close()


# ---------------------------------------------------------------------------
# query engine: read-only + authorizer + views
# ---------------------------------------------------------------------------
async def test_query_select_project_filter(tmp_path):
    db, path = _setup_db(tmp_path)
    s1 = ShownFindingsStore(db, "pid-1")
    s2 = ShownFindingsStore(db, "pid-2")
    await s1.record_shown(_make_finding("fp-1"))
    await s2.record_shown(_make_finding("fp-2"))

    result = run_query(path, "SELECT fingerprint FROM v_findings", None, "pid-1")
    assert result["row_count"] == 1
    assert result["rows"][0]["fingerprint"] == "fp-1"
    assert "WHERE project_id = 'pid-1'" in result["sql"]
    db.close()


async def test_query_auto_limit(tmp_path):
    db, path = _setup_db(tmp_path)
    result = run_query(path, "SELECT * FROM v_findings", None, "pid-1")
    assert "LIMIT 1000" in result["sql"]
    db.close()


async def test_query_auto_limit_not_doubled(tmp_path):
    db, path = _setup_db(tmp_path)
    result = run_query(path, "SELECT * FROM v_findings LIMIT 5", None, "pid-1")
    assert result["sql"].count("LIMIT") == 1
    db.close()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE v_findings SET severity='low'",
        "DELETE FROM v_findings",
        "INSERT INTO v_findings VALUES (1)",
        "ATTACH DATABASE 'x' AS y",
        "PRAGMA table_info(v_findings)",
        "DROP TABLE v_findings",
    ],
)
async def test_query_rejects_writes(tmp_path, sql):
    db, path = _setup_db(tmp_path)
    with pytest.raises(ReadOnlyQueryError):
        run_query(path, sql, None, "pid-1")
    db.close()


async def test_query_rejects_multi_statement(tmp_path):
    db, path = _setup_db(tmp_path)
    with pytest.raises(ReadOnlyQueryError, match="single statement"):
        run_query(path, "SELECT * FROM v_findings; SELECT * FROM v_findings", None, "pid-1")
    db.close()


async def test_query_rejects_non_view_table(tmp_path):
    db, path = _setup_db(tmp_path)
    with pytest.raises(ReadOnlyQueryError, match="not an allowed view"):
        run_query(path, "SELECT * FROM shown_findings", None, "pid-1")
    db.close()


async def test_query_rejects_comma_join_to_raw_table(tmp_path):
    """Запятая в FROM не должна обходить allowlist (shown_findings — не view)."""
    db, path = _setup_db(tmp_path)
    with pytest.raises(ReadOnlyQueryError, match="not an allowed view"):
        run_query(path, "SELECT * FROM v_findings, shown_findings", None, "pid-1")
    db.close()


async def test_query_rejects_subquery_from(tmp_path):
    db, path = _setup_db(tmp_path)
    with pytest.raises(ReadOnlyQueryError, match="subqueries in FROM/JOIN"):
        run_query(path, "SELECT * FROM (SELECT * FROM v_findings)", None, "pid-1")
    db.close()


async def test_query_or_does_not_leak_other_project(tmp_path):
    """Автофильтр project_id не должен ослабляться оператором OR."""
    db, path = _setup_db(tmp_path)
    await ShownFindingsStore(db, "pid-1").record_shown(_make_finding("fp-1"))
    await ShownFindingsStore(db, "pid-2").record_shown(_make_finding("fp-2"))

    result = run_query(
        path,
        "SELECT fingerprint FROM v_findings WHERE severity='high' OR severity='low'",
        None,
        "pid-1",
    )
    fps = [row["fingerprint"] for row in result["rows"]]
    assert fps == ["fp-1"]
    assert "severity='high' OR severity='low')" in result["sql"]
    db.close()


async def test_finalize_keeps_group_by_outside_where_parens():
    """WHERE + GROUP BY/ORDER BY: хвостовые клаузы остаются вне скобок предиката."""
    sql = "SELECT severity, COUNT(*) AS n FROM v_findings WHERE status = 'SHOWN' GROUP BY severity ORDER BY n DESC"
    finalized = _finalize(sql, "pid-1")
    assert "WHERE project_id = 'pid-1' AND (status = 'SHOWN')" in finalized
    assert "GROUP BY severity" in finalized
    assert "ORDER BY n DESC" in finalized
    # Скобка предиката закрыта до GROUP BY.
    assert finalized.index(")") < finalized.index("GROUP BY")


async def test_finalize_where_and_existing_limit():
    """WHERE + LIMIT: LIMIT остаётся снаружи, авто-LIMIT не дублируется."""
    sql = "SELECT * FROM v_findings WHERE status = 'SHOWN' LIMIT 5"
    finalized = _finalize(sql, "pid-1")
    assert "AND (status = 'SHOWN')" in finalized
    assert finalized.count("LIMIT") == 1


async def test_query_group_by_with_where(tmp_path):
    """Агрегация по severities работает и учитывает автофильтр проекта."""
    db, path = _setup_db(tmp_path)
    await ShownFindingsStore(db, "pid-1").record_shown(_make_finding("fp-1"))
    low = _make_finding("fp-2")
    low.severity = Severity.LOW
    await ShownFindingsStore(db, "pid-1").record_shown(low)
    await ShownFindingsStore(db, "pid-2").record_shown(_make_finding("fp-3"))

    result = run_query(
        path,
        "SELECT severity, COUNT(*) AS n FROM v_findings WHERE status = 'SHOWN' GROUP BY severity ORDER BY n DESC",
        None,
        "pid-1",
    )
    assert result["row_count"] == 2  # только pid-1, без находки другого проекта
    counts = {row["severity"]: row["n"] for row in result["rows"]}
    assert counts == {"high": 1, "low": 1}
    db.close()


async def test_query_group_by_having(tmp_path):
    """HAVING идёт после GROUP BY и не попадает внутрь скобок WHERE."""
    db, path = _setup_db(tmp_path)
    await ShownFindingsStore(db, "pid-1").record_shown(_make_finding("fp-1"))
    low = _make_finding("fp-2")
    low.severity = Severity.LOW
    await ShownFindingsStore(db, "pid-1").record_shown(low)

    result = run_query(
        path,
        "SELECT severity, COUNT(*) AS n FROM v_findings WHERE status = 'SHOWN' GROUP BY severity HAVING COUNT(*) > 1",
        None,
        "pid-1",
    )
    assert result["row_count"] == 0
    db.close()


async def test_query_rejects_non_select(tmp_path):
    db, path = _setup_db(tmp_path)
    with pytest.raises(ReadOnlyQueryError, match="only SELECT"):
        run_query(path, "EXPLAIN SELECT * FROM v_findings", None, "pid-1")
    db.close()


async def test_query_v_summary_and_v_projects(tmp_path):
    db, path = _setup_db(tmp_path)
    await ShownFindingsStore(db, "pid-1").record_shown(_make_finding("fp-1"))

    summary = run_query(path, "SELECT * FROM v_summary", None, "pid-1")
    assert summary["row_count"] >= 1

    projects = run_query(path, "SELECT * FROM v_projects", None, "pid-1")
    assert isinstance(projects["rows"], list)


# ---------------------------------------------------------------------------
# sql_audit_log
# ---------------------------------------------------------------------------
async def test_sql_audit_log_records(tmp_path):
    db, _ = _setup_db(tmp_path)
    store = SqlAuditLogStore(db)
    await store.record("pid-1", "sess-1", "SELECT * FROM v_findings", 12, 3)
    rows = db._fetchall("SELECT * FROM sql_audit_log")
    assert len(rows) == 1
    assert rows[0]["project_id"] == "pid-1"
    assert rows[0]["session_id"] == "sess-1"
    assert rows[0]["row_count"] == 3
    db.close()


# ---------------------------------------------------------------------------
# announce-only scan_project
# ---------------------------------------------------------------------------
class _FakeScanner(BaseScanner):
    name = "fake"

    def __init__(self, findings, **kw):
        super().__init__(**kw)
        self._findings = findings

    async def is_available(self) -> bool:
        return True

    async def scan(self, files, mode):
        return list(self._findings)


def _rf() -> RawFinding:
    return RawFinding(
        rule_id="r",
        raw_severity="high",
        file_path="a.py",
        scanner="fake",
        snippet="x = 1",
        category=Category.SAST,
    )


async def test_scan_persist_false_does_not_mark_shown(tmp_path, default_config):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    registry = ScannerRegistry()
    registry.register(_FakeScanner([_rf()]))
    db, _ = _setup_db(tmp_path)
    shown = ShownFindingsStore(db, "p1")

    coord = ScanCoordinator(
        default_config,
        registry,
        shown_store=shown,
        project_root=str(tmp_path),
        project_id="p1",
    )
    result = await coord.scan(["a.py"], mode="project", persist=False)
    assert result.total == 1
    assert await shown.get_all(limit=100) == []

    persisted = await coord.scan(["a.py"], mode="project")
    assert await shown.get_all(limit=100)
    assert persisted.total == 1
    db.close()


async def test_build_announce_output():
    findings = [
        Finding(
            fingerprint=f"fp-{i}",
            rule_id="r",
            severity=Severity.HIGH if i < 2 else Severity.LOW,
            file_path="a.py",
            scanner="semgrep",
            category=Category.SAST,
        )
        for i in range(25)
    ]
    result = ScanResult(findings=findings)

    state = server.SessionState()
    state.project_id = "pid-1"
    state.project_alias = "app"
    out = await server._build_announce_output(state, result)

    assert out["project"] == {"project_id": "pid-1", "project_alias": "app"}
    assert out["summary"]["total"] == 25
    assert out["summary"]["by_severity"]["high"] == 2
    assert out["summary"]["by_file_top10"][0]["count"] == 25
    assert len(out["top_findings"]) == 20
    assert out["truncated"] is True
    assert out["total_available"] == 25


# ---------------------------------------------------------------------------
# get_fix_context_batch limit
# ---------------------------------------------------------------------------
async def test_get_fix_context_batch_limit(tmp_path, monkeypatch):
    db = Database(tmp_path / "shown.db")
    db.connect()
    store = FindingContextStore(db)
    store.init_schema()
    builder = ContextBuilder(store, project_root=str(tmp_path), project_id="pid-1")

    class Stub:
        pass

    s = Stub()
    s.context_builder = builder

    async def ensure(project_path=None):
        return s

    monkeypatch.setattr(server, "_ensure_session", ensure)

    out = await server.get_fix_context_batch(["f1"] * 21)
    assert out["status"] == "error"
    assert "20" in out["reason"]
    db.close()


# ---------------------------------------------------------------------------
# export_snapshot
# ---------------------------------------------------------------------------
async def test_export_snapshot_parquet_error(tmp_path, monkeypatch):
    class Stub:
        pass

    s = Stub()
    s.project_id = "pid-1"
    s.databases = {"shown": None}

    async def ensure(project_path=None):
        return s

    monkeypatch.setattr(server, "_ensure_session", ensure)
    out = await server.export_snapshot(str(tmp_path / "x.parquet"), format="parquet")
    assert out["status"] == "error"
    assert "ndjson" in out["reason"]


async def test_export_snapshot_ndjson(tmp_path, monkeypatch):
    db, _ = _setup_db(tmp_path)
    s1 = ShownFindingsStore(db, "pid-1")
    await s1.record_shown(_make_finding("fp-1"))

    class Stub:
        pass

    s = Stub()
    s.project_id = "pid-1"
    s.databases = {"shown": db}

    async def ensure(project_path=None):
        return s

    monkeypatch.setattr(server, "_ensure_session", ensure)
    target = tmp_path / "out.ndjson"
    out = await server.export_snapshot(str(target), format="ndjson")
    assert out["status"] == "ok"
    assert out["rows"] == 1
    assert target.exists()
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["fingerprint"] == "fp-1"
    db.close()


async def test_export_snapshot_unsupported_format(tmp_path, monkeypatch):
    class Stub:
        pass

    s = Stub()
    s.project_id = "pid-1"
    s.databases = {"shown": None}

    async def ensure(project_path=None):
        return s

    monkeypatch.setattr(server, "_ensure_session", ensure)
    out = await server.export_snapshot(str(tmp_path / "x.csv"), format="csv")
    assert out["status"] == "error"
    assert "unsupported" in out["reason"]


# ---------------------------------------------------------------------------
# _finalize project-filter injection
# ---------------------------------------------------------------------------
def test_finalize_injects_where():
    out = _finalize("SELECT * FROM v_findings WHERE severity='high'", "abc")
    assert "WHERE project_id = 'abc' AND (severity='high')" in out
    assert out.endswith("LIMIT 1000")


def test_finalize_wraps_where_with_or():
    out = _finalize("SELECT * FROM v_findings WHERE severity='high' OR severity='low'", "abc")
    assert "WHERE project_id = 'abc' AND (severity='high' OR severity='low')" in out


def test_finalize_appends_where_before_limit():
    out = _finalize("SELECT * FROM v_findings ORDER BY severity", "abc")
    assert "WHERE project_id = 'abc'" in out
    assert out.endswith("ORDER BY severity LIMIT 1000")
