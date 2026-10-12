"""Тесты PR 1.2+1.4: стабильный ``logical_id`` и Redactor.

Покрывает:
  * ``compute_logical_id``: детерминизм, изоляция по AST-scope,
    fallback на bucket по 20 строк для не-Python/ошибочного исходника;
  * ``Redactor``: полная маска snippet у ``secret``, вычищение паттернов
    и high-entropy в прочих категориях, рекурсивная redaction metadata;
  * ``FindingIdentityStore.upsert``: ``first_seen_at`` сохраняется при
    повторном показе, ``last_fingerprint`` обновляется.
"""

from __future__ import annotations

import pytest

from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.normalization.redactor import Redactor
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.logical_id import compute_logical_id, extract_scope_key
from appsecgate_mcp.storage.stores import FindingIdentityStore


# ----------------------------------------------------------------------
# logical_id
# ----------------------------------------------------------------------
def test_extract_scope_key_py_function():
    src = "def top():\n    def inner():\n        x = 1\n    return inner\n"
    assert extract_scope_key(src, 3) == "inner"
    assert extract_scope_key(src, 1) == "top"


def test_extract_scope_key_non_python_returns_none():
    assert extract_scope_key("<html><body>hi</body></html>", 1) is None
    assert extract_scope_key("", 1) is None


def test_extract_scope_key_syntax_error_returns_none():
    assert extract_scope_key("def broken(:\n", 1) is None


def test_compute_logical_id_stable_across_line_shifts():
    rule, fpath = "hardcoded-secret", "app.py"
    src_before = "def a():\n    secret = 'x'\n"
    src_after = "\n" * 100 + src_before
    lid_before = compute_logical_id(rule, fpath, 2, src_before)
    lid_after = compute_logical_id(rule, fpath, 102, src_after)
    assert lid_before == lid_after
    assert len(lid_before) == 16


def test_compute_logical_id_isolates_scopes():
    rule, fpath = "hardcoded-secret", "app.py"
    src = "def foo():\n    pass\n\ndef bar():\n    pass\n"
    lid_foo = compute_logical_id(rule, fpath, 1, src)
    lid_bar = compute_logical_id(rule, fpath, 4, src)
    assert lid_foo != lid_bar


def test_compute_logical_id_bucket_fallback():
    rule, fpath = "any-rule", "notes.txt"
    src = "line1\nline2\nline3\nline4\nline5\n"
    lid_a = compute_logical_id(rule, fpath, 2, src)
    lid_b = compute_logical_id(rule, fpath, 5, src)
    assert lid_a == lid_b
    lid_c = compute_logical_id(rule, fpath, 22, src)
    assert lid_a != lid_c


# ----------------------------------------------------------------------
# Redactor
# ----------------------------------------------------------------------
def _finding(**kw) -> Finding:
    base = dict(
        fingerprint="fp",
        rule_id="r",
        severity=Severity.HIGH,
        file_path="app.py",
        scanner="gitleaks",
        category=Category.SECRET,
        snippet="aws_access_key_id = AKIAIOSFODNN7EXAMPLE",
    )
    base.update(kw)
    return Finding(**base)


def test_redactor_masks_secret_snippet_entirely():
    redactor = Redactor()
    finding = _finding()
    redacted, changed = redactor.redact_finding(finding)
    assert changed
    assert redacted.snippet == "[REDACTED]"
    assert "AKIA" not in redacted.snippet


def test_redactor_masks_aws_key_in_sast_snippet():
    redactor = Redactor()
    finding = _finding(
        category=Category.SAST,
        snippet="key = 'AKIAIOSFODNN7EXAMPLE'; use(key)",
    )
    redacted, changed = redactor.redact_finding(finding)
    assert changed
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted.snippet
    assert "use(key)" in redacted.snippet


def test_redactor_masks_jwt():
    redactor = Redactor()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijklmnopqrstuvwxyz123456"
    finding = _finding(category=Category.SAST, snippet=jwt)
    redacted, changed = redactor.redact_finding(finding)
    assert changed
    assert "eyJ" not in redacted.snippet


def test_redactor_masks_high_entropy_token():
    redactor = Redactor()
    finding = _finding(category=Category.SAST, snippet="token = 'p4ckQv9XxZr7LmN3tYhB2wSdF8c'")
    redacted, changed = redactor.redact_finding(finding)
    assert changed
    assert "[REDACTED]" in redacted.snippet


def test_redactor_masks_nested_metadata():
    redactor = Redactor()
    finding = _finding(
        category=Category.SAST,
        snippet="safe code",
        metadata={"vuln": {"match": "AKIAIOSFODNN7EXAMPLE"}, "list": ["x", "AKIAIOSFODNN7EXAMPLE"]},
    )
    redacted, changed = redactor.redact_finding(finding)
    assert changed
    assert "AKIA" not in str(redacted.metadata)


def test_redactor_does_not_mask_plain_sast_snippet():
    redactor = Redactor()
    finding = _finding(category=Category.SAST, snippet="def foo():\n    return 1")
    redacted, changed = redactor.redact_finding(finding)
    assert not changed
    assert redacted.snippet == "def foo():\n    return 1"


# ----------------------------------------------------------------------
# FindingIdentityStore.upsert
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_finding_identity_preserves_first_seen_at(tmp_path, monkeypatch):
    from appsecgate_mcp.storage import stores as stores_mod

    clock = {"t": 0}

    def fake_now() -> str:
        clock["t"] += 1
        return f"2026-01-01T00:00:{clock['t']:02d}+00:00"

    monkeypatch.setattr(stores_mod, "_now_iso", fake_now)

    db = Database(tmp_path / "shown.db")
    db.connect()
    store = FindingIdentityStore(db)
    store.init_schema()

    await store.upsert("p1", "lid-1", "rule", "app.py", "fp-1")
    await store.upsert("p1", "lid-1", "rule", "app.py", "fp-2")

    rows = await db.fetchall(
        "SELECT * FROM finding_identity WHERE project_id = 'p1' AND logical_id = 'lid-1'"
    )
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["first_seen_at"] == "2026-01-01T00:00:01+00:00"
    assert row["last_fingerprint"] == "fp-2"
    assert row["last_seen_at"] == "2026-01-01T00:00:02+00:00"

    db.close()
