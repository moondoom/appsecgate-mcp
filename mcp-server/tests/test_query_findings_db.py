"""Тесты query-движка: query_findings_db (views, read-only), sql_audit_log, export_snapshot.

Вынесено из ``test_context_and_query.py`` при рефакторинге по AGENTS.md
«File Size Limits» — контекстные тесты остались в исходном файле.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from appsecgate_mcp import server
from appsecgate_mcp.models.finding import Category, Finding, Severity
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
    sql = (
        "SELECT severity, COUNT(*) AS n FROM v_findings "
        "WHERE status = 'SHOWN' GROUP BY severity ORDER BY n DESC"
    )
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
        "SELECT severity, COUNT(*) AS n FROM v_findings "
        "WHERE status = 'SHOWN' GROUP BY severity ORDER BY n DESC",
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
        "SELECT severity, COUNT(*) AS n FROM v_findings "
        "WHERE status = 'SHOWN' GROUP BY severity HAVING COUNT(*) > 1",
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


# ---------------------------------------------------------------------------
# finding_identity join (ADR-0005 §2.8, К1)
# ---------------------------------------------------------------------------
async def test_finding_identity_join_in_views(tmp_path):
    """v_findings/find() берут logical_id джойном через finding_identity по fingerprint."""
    db, path = _setup_db(tmp_path)
    shown = ShownFindingsStore(db, "pid-1")
    await shown.record_shown(_make_finding("fp-1"), logical_id="lid-1")
    await shown.record_shown(_make_finding("fp-2"), logical_id="lid-2")

    # v_findings: first_seen_at приходит из finding_identity (джойн по fingerprint).
    rows = run_query(
        path,
        "SELECT fingerprint, first_seen_at FROM v_findings ORDER BY fingerprint",
        None,
        "pid-1",
    )
    assert rows["row_count"] == 2
    assert all(r["first_seen_at"] for r in rows["rows"])

    # find(): и по fingerprint, и по logical_id через finding_identity.
    by_fp = await shown.find("fp-1")
    assert by_fp is not None and by_fp["logical_id"] == "lid-1"
    by_lid = await shown.find("lid-2")
    assert by_lid is not None and by_lid["fingerprint"] == "fp-2"

    # «Прыжок» fingerprint: тот же logical_id на новом fingerprint (К1).
    await shown.record_shown(_make_finding("fp-1b"), logical_id="lid-1")
    jumped = await shown.find("lid-1")
    assert jumped is not None and jumped["fingerprint"] == "fp-1b"
    assert jumped["logical_id"] == "lid-1"
    db.close()

