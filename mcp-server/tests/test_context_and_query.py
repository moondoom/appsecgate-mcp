"""Тесты этапа 1 (хвост 1.4–1.9): ContextBuilder, announce-only scan_project.

Query-движок (query_findings_db, sql_audit_log, export_snapshot) вынесен
в ``test_query_findings_db.py`` — см. AGENTS.md «File Size Limits».
"""

from __future__ import annotations

import json
from pathlib import Path

from appsecgate_mcp import server
from appsecgate_mcp.models.finding import Category, Finding, ScanResult, Severity
from appsecgate_mcp.orchestration.context_builder import ContextBuilder
from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.registry import ScannerRegistry
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.query import init_views
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
