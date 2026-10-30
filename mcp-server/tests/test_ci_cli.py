"""Тесты CI-режима (ADR-0003): exit 0/1/2, snapshot, ndjson, git diff vs base.

Сканеры — фейковые (без бинарников), git — реальный временный репозиторий.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from appsecgate_mcp.models.finding import Category
from appsecgate_mcp.normalization.fingerprint import FingerprintGenerator
from appsecgate_mcp.orchestration.ci import run_ci
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.registry import ScannerRegistry
from appsecgate_mcp.server.ci import ci_main


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


class _FakeScanner(BaseScanner):
    name = "fake"

    def __init__(self, findings, *, available: bool = True) -> None:
        super().__init__()
        self._findings = findings
        self._available = available

    async def is_available(self) -> bool:
        return self._available

    async def scan(self, files, mode):
        # Как реальные сканеры: находки только по запрошенным файлам.
        return [rf for rf in self._findings if rf.file_path in files]


def _fake_registry(findings, *, available: bool = True) -> ScannerRegistry:
    registry = ScannerRegistry()
    registry.register(_FakeScanner(findings, available=available))
    return registry


def _rf(
    *,
    rule_id: str = "r",
    raw_severity: str = "low",
    file_path: str = "b.py",
    snippet: str = "x = 1",
) -> RawFinding:
    return RawFinding(
        rule_id=rule_id,
        raw_severity=raw_severity,
        file_path=file_path,
        scanner="fake",
        snippet=snippet,
        category=Category.SAST,
    )


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "base.txt").write_text("base\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    _git(root, "branch", "base")  # базовая точка для diff base...HEAD
    return root


def _commit_file(root, name: str, content: str) -> None:
    (root / name).write_text(content)
    _git(root, "add", name)
    _git(root, "commit", "-m", f"add {name}")


def _write_snapshot(tmp_path, fp: str, **extra) -> str:
    path = tmp_path / "shown.ndjson"
    record = {
        "fp": fp,
        "rule_id": "r",
        "file": "b.py",
        "line": 1,
        "severity": "low",
        "shown_at": "2026-10-01T00:00:00Z",
        "verified_status": None,
        "suppression_scope": None,
        **extra,
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return str(path)


@pytest.mark.asyncio
async def test_ci_pass_medium_finding(repo):
    _commit_file(repo, "b.py", "b = 1\n")
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 0
    assert result.summary.total == 1
    assert result.summary.block_count == 0


@pytest.mark.asyncio
async def test_ci_blocks_high_finding(repo):
    _commit_file(repo, "b.py", "b = 1\n")
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        registry=_fake_registry([_rf(raw_severity="high")]),
    )
    assert result.exit_code == 1
    assert result.summary.blocked[0].reason == "ci_severity"


@pytest.mark.asyncio
async def test_ci_blocks_unresolved_local_from_snapshot(repo, tmp_path):
    _commit_file(repo, "b.py", "b = 1\n")
    fp = FingerprintGenerator().generate_for("r", "b.py", "x = 1")
    snapshot = _write_snapshot(tmp_path, fp)
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        shown_snapshot=snapshot,
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 1
    assert result.summary.blocked[0].reason == "unresolved_local"


@pytest.mark.asyncio
async def test_ci_fixed_snapshot_clears_block(repo, tmp_path):
    _commit_file(repo, "b.py", "b = 1\n")
    fp = FingerprintGenerator().generate_for("r", "b.py", "x = 1")
    snapshot = _write_snapshot(tmp_path, fp, verified_status="fixed")
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        shown_snapshot=snapshot,
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 0
    assert result.summary.block_count == 0


@pytest.mark.asyncio
async def test_ci_missing_snapshot_is_warning_only(repo, tmp_path):
    _commit_file(repo, "b.py", "b = 1\n")
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        shown_snapshot=str(tmp_path / "nope.ndjson"),
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 0
    assert any("shown snapshot not found" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_ci_missing_snapshot_fails_closed_when_required(repo, tmp_path):
    _commit_file(repo, "b.py", "b = 1\n")
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        shown_snapshot=str(tmp_path / "nope.ndjson"),
        require_shown_snapshot=True,
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 2
    assert "shown snapshot not found" in result.error


@pytest.mark.asyncio
async def test_ci_unknown_base_ref_exit_2(repo):
    _commit_file(repo, "b.py", "b = 1\n")
    result = await run_ci(
        project_path=str(repo),
        base_ref="no-such-ref",
        registry=_fake_registry([_rf()]),
    )
    assert result.exit_code == 2
    assert "git error" in result.error


@pytest.mark.asyncio
async def test_ci_no_available_scanners_exit_2(repo):
    _commit_file(repo, "b.py", "b = 1\n")
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        registry=_fake_registry([_rf()], available=False),
    )
    assert result.exit_code == 2
    assert "no scanners available" in result.error


@pytest.mark.asyncio
async def test_ci_empty_diff_passes(repo):
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        registry=_fake_registry([_rf()]),
    )
    assert result.exit_code == 0
    assert result.summary.total == 0


def test_ci_main_ndjson_blocked(repo, capsys):
    _commit_file(repo, "b.py", "b = 1\n")
    code = ci_main(
        ["--project", str(repo), "--base-ref", "base", "--format", "ndjson"],
        registry=_fake_registry([_rf(raw_severity="high")]),
    )
    assert code == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert lines[0]["type"] == "summary"
    assert lines[0]["blocked"] == 1
    finding = next(line for line in lines if line["type"] == "finding")
    assert finding["decision"] == "block"
    assert finding["reason"] == "ci_severity"


def test_ci_main_text_pass(repo, capsys):
    _commit_file(repo, "b.py", "b = 1\n")
    code = ci_main(
        ["--project", str(repo), "--base-ref", "base"],
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "result: pass" in out
    assert "BLOCK" not in out
