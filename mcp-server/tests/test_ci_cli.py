"""Тесты CI-режима (ADR-0004 MS-6): exit 0/1/2, master-источник, ndjson, git diff.

Сканеры — фейковые (без бинарников), git — реальный временный репозиторий.
Запросы к master мокаются на уровне `fetch_findings` (контракт самого
`fetch_findings` проверяется в test_shown_source.py end-to-end).
"""

from __future__ import annotations

import json
import subprocess

import pytest

from appsecgate_mcp.models.finding import Category
from appsecgate_mcp.normalization.fingerprint import FingerprintGenerator
from appsecgate_mcp.orchestration import ci as ci_module
from appsecgate_mcp.orchestration.ci import run_ci
from appsecgate_mcp.orchestration.shown_source import MasterFindingsError, ShownRecord
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


@pytest.fixture()
def master(monkeypatch):
    """Мокает `fetch_findings` в CI-модуле: возвращает записи или кидает ошибку."""

    def _install(records: list[ShownRecord] | None = None, error: str | None = None):
        if error:

            def _fetch(*args, **kwargs):
                raise MasterFindingsError(error)

        else:

            def _fetch(*args, **kwargs):
                return records or []

        monkeypatch.setattr(ci_module, "fetch_findings", _fetch)

    return _install


@pytest.mark.asyncio
async def test_ci_pass_medium_finding(repo, master):
    _commit_file(repo, "b.py", "b = 1\n")
    master()
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        master_url="http://master.test",
        project_id="p1",
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 0
    assert result.summary.total == 1
    assert result.summary.block_count == 0


@pytest.mark.asyncio
async def test_ci_blocks_high_finding(repo, master):
    _commit_file(repo, "b.py", "b = 1\n")
    master()
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        master_url="http://master.test",
        project_id="p1",
        registry=_fake_registry([_rf(raw_severity="high")]),
    )
    assert result.exit_code == 1
    assert result.summary.blocked[0].reason == "ci_severity"


@pytest.mark.asyncio
async def test_ci_blocks_unresolved_local_from_master(repo, master):
    _commit_file(repo, "b.py", "b = 1\n")
    fp = FingerprintGenerator().generate_for("r", "b.py", "x = 1")
    master(records=[ShownRecord(fingerprint=fp, status="SHOWN")])
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        master_url="http://master.test",
        project_id="p1",
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 1
    assert result.summary.blocked[0].reason == "unresolved_local"


@pytest.mark.asyncio
async def test_ci_fixed_master_clears_block(repo, master):
    _commit_file(repo, "b.py", "b = 1\n")
    fp = FingerprintGenerator().generate_for("r", "b.py", "x = 1")
    master(records=[ShownRecord(fingerprint=fp, verified_status="fixed")])
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        master_url="http://master.test",
        project_id="p1",
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 0
    assert result.summary.block_count == 0


@pytest.mark.asyncio
async def test_ci_without_master_exit_2(repo):
    _commit_file(repo, "b.py", "b = 1\n")
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 2
    assert "ci requires master" in result.error


@pytest.mark.asyncio
async def test_ci_without_project_id_exit_2(repo):
    _commit_file(repo, "b.py", "b = 1\n")
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        master_url="http://master.test",
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 2
    assert "project id" in result.error


@pytest.mark.asyncio
async def test_ci_master_unavailable_exit_2(repo, master):
    _commit_file(repo, "b.py", "b = 1\n")
    master(error="GET /v1/findings: HTTP 500")
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        master_url="http://master.test",
        project_id="p1",
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    assert result.exit_code == 2
    assert "HTTP 500" in result.error


@pytest.mark.asyncio
async def test_ci_unknown_base_ref_exit_2(repo):
    _commit_file(repo, "b.py", "b = 1\n")
    result = await run_ci(
        project_path=str(repo),
        base_ref="no-such-ref",
        master_url="http://master.test",
        project_id="p1",
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
        master_url="http://master.test",
        project_id="p1",
        registry=_fake_registry([_rf()], available=False),
    )
    assert result.exit_code == 2
    assert "no scanners available" in result.error


@pytest.mark.asyncio
async def test_ci_empty_diff_passes(repo, master):
    master()
    result = await run_ci(
        project_path=str(repo),
        base_ref="base",
        master_url="http://master.test",
        project_id="p1",
        registry=_fake_registry([_rf()]),
    )
    assert result.exit_code == 0
    assert result.summary.total == 0


def test_ci_main_ndjson_blocked(repo, capsys, master):
    _commit_file(repo, "b.py", "b = 1\n")
    master()
    code = ci_main(
        [
            "--project",
            str(repo),
            "--base-ref",
            "base",
            "--master-url",
            "http://master.test",
            "--project-id",
            "p1",
            "--format",
            "ndjson",
        ],
        registry=_fake_registry([_rf(raw_severity="high")]),
    )
    assert code == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert lines[0]["type"] == "summary"
    assert lines[0]["blocked"] == 1
    finding = next(line for line in lines if line["type"] == "finding")
    assert finding["decision"] == "block"
    assert finding["reason"] == "ci_severity"


def test_ci_main_text_pass(repo, capsys, master):
    _commit_file(repo, "b.py", "b = 1\n")
    master()
    code = ci_main(
        [
            "--project",
            str(repo),
            "--base-ref",
            "base",
            "--master-url",
            "http://master.test",
            "--project-id",
            "p1",
        ],
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "result: pass" in out
    assert "BLOCK" not in out


def test_ci_main_without_master_fails_closed(repo, capsys, master):
    _commit_file(repo, "b.py", "b = 1\n")
    master()
    code = ci_main(
        ["--project", str(repo), "--base-ref", "base"],
        registry=_fake_registry([_rf(raw_severity="medium")]),
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "ci requires master" in out
