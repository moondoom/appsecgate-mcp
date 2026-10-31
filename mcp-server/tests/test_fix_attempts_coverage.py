"""Регрессия: fix_attempts.coverage считал logical_id из shown_findings,
где этой колонки нет (ADR-0005 §2.8, К1) — падало 'no such column: logical_id'.
Считаем уникальные находки через finding_identity, как view v_verification_coverage.
"""

from __future__ import annotations

import pytest

from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores import (
    FindingIdentityStore,
    FixAttemptsStore,
    ShownFindingsStore,
)

pytestmark = pytest.mark.asyncio


def _finding(fp: str) -> Finding:
    return Finding(
        fingerprint=fp,
        rule_id="test.rule",
        severity=Severity.HIGH,
        file_path="a.py",
        scanner="semgrep",
        category=Category.SAST,
    )


async def test_coverage_counts_through_finding_identity(tmp_path):
    db = Database(tmp_path / "shown.db")
    db.connect()
    shown = ShownFindingsStore(db, "pid-1")
    shown.init_schema()
    FindingIdentityStore(db).init_schema()
    attempts = FixAttemptsStore(db)
    attempts.init_schema()

    await shown.record_shown(_finding("fp-1"), logical_id="lid-1")
    await shown.record_shown(_finding("fp-2"), logical_id="lid-2")
    await attempts.record(
        project_id="pid-1", logical_id="lid-1", fingerprint="fp-1",
        rule_id="test.rule", file_path="a.py", reported_status="fixed",
        verified_status="fixed", note="", session_id="sess-1",
    )

    assert await attempts.coverage("pid-1") == {"attempts": 1, "total": 2}
    db.close()
