"""Тесты ScanCoordinator с фейковым сканером (без бинарников)."""

from __future__ import annotations

import pytest

from appsecgate_mcp.models.finding import Category
from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.registry import ScannerRegistry


class FakeScanner(BaseScanner):
    name = "fake"

    def __init__(
        self,
        findings,
        *,
        scanner_name: str | None = None,
        available=True,
        boom=False,
        **kw,
    ):
        super().__init__(**kw)
        self._findings = findings
        self._available = available
        self._boom = boom
        if scanner_name:
            self.name = scanner_name

    async def is_available(self) -> bool:
        return self._available

    async def scan(self, files, mode):
        if self._boom:
            raise RuntimeError("scanner crashed")
        return list(self._findings)


def rf(**kw) -> RawFinding:
    base = dict(
        rule_id="r",
        raw_severity="high",
        file_path="a.py",
        scanner="fake",
        snippet="x = 1",
        category=Category.SAST,
    )
    base.update(kw)
    return RawFinding(**base)


@pytest.mark.asyncio
async def test_scan_normalizes_and_fingerprints(default_config):
    registry = ScannerRegistry()
    registry.register(FakeScanner([rf()]))
    coord = ScanCoordinator(default_config, registry)
    result = await coord.scan(["a.py"], mode="file")
    assert result.total == 1
    assert result.findings[0].fingerprint
    assert result.findings[0].scanner == "fake"


@pytest.mark.asyncio
async def test_unavailable_scanner_skipped(default_config):
    registry = ScannerRegistry()
    registry.register(FakeScanner([rf()], available=False))
    coord = ScanCoordinator(default_config, registry)
    result = await coord.scan(["a.py"])
    assert result.total == 0
    assert "fake" in result.meta.scanners_skipped


@pytest.mark.asyncio
async def test_crashing_scanner_isolated(default_config):
    registry = ScannerRegistry()
    registry.register(FakeScanner([rf()], boom=True))
    coord = ScanCoordinator(default_config, registry)
    result = await coord.scan(["a.py"])
    assert result.total == 0
    assert any(e.scanner == "fake" for e in result.meta.errors)


@pytest.mark.asyncio
async def test_diff_excludes_deleted_files(default_config, tmp_path):
    """Регрессия B5: удалённые файлы из git-diff не передаются сканерам.

    semgrep падает (rc!=0) на несуществующем таргете и теряет весь пакет
    SAST-находок, поэтому deleted-файлы фильтруются до планирования сканеров.
    """
    (tmp_path / "existing.py").write_text("x = 1\n")

    seen: list[list[str]] = []

    class RecordingScanner(FakeScanner):
        async def scan(self, files, mode):
            seen.append(list(files))
            return [rf(file_path="existing.py", snippet="x = 1")]

    registry = ScannerRegistry()
    registry.register(RecordingScanner([], scanner_name="semgrep"))
    coord = ScanCoordinator(default_config, registry, project_root=str(tmp_path))
    result = await coord.scan(["existing.py", "deleted.py"], mode="diff")

    assert seen == [["existing.py"]]
    assert result.meta.scanned_files == ["existing.py"]
    assert result.total == 1
    assert any("deleted" in w for w in result.meta.warnings)


@pytest.mark.asyncio
async def test_scan_dedups_same_secret_across_scanners(default_config):
    """Регрессия T1: Gitleaks и TruffleHog на одном секрете — одна находка."""
    registry = ScannerRegistry()
    registry.register(
        FakeScanner(
            [
                rf(
                    scanner="gitleaks",
                    rule_id="aws-access-token",
                    line_start=5,
                    snippet='key = "AKIAIOSFODNN7EXAMPLE"',
                    category=Category.SECRET,
                    metadata={"Secret": "AKIAIOSFODNN7EXAMPLE"},
                )
            ],
            scanner_name="gitleaks",
        )
    )
    registry.register(
        FakeScanner(
            [
                rf(
                    scanner="trufflehog",
                    rule_id="AWS",
                    raw_severity="medium",
                    line_start=9,
                    snippet="AKIAIOSFODNN7EXAMPLE",
                    category=Category.SECRET,
                )
            ],
            scanner_name="trufflehog",
        )
    )
    coord = ScanCoordinator(default_config, registry)
    result = await coord.scan(["a.py"], mode="file")
    assert result.total == 1
    # Больший severity (gitleaks=high, trufflehog=medium) побеждает.
    assert result.findings[0].scanner == "gitleaks"


@pytest.mark.asyncio
async def test_scan_fingerprints_stable_across_runs(default_config):
    """Регрессия T10: два скана одного файла → идентичный набор fingerprint.

    Фейковый gitleaks отдаёт находки в разном порядке между прогонами
    (как реальный Gitleaks: то github-pat, то generic-api-key первым).
    Детерминированный дедуп даёт одного «выжившего», поэтому fingerprint
    не «плывёт» между сканами (ADR-0001 §3.2).
    """

    def findings(rule_first: str) -> list[RawFinding]:
        common = dict(
            scanner="gitleaks",
            raw_severity="high",
            file_path="a.py",
            line_start=5,
            snippet='token = "ghp_12345"',
            category=Category.SECRET,
            metadata={"Secret": "ghp_12345"},
        )
        first, second = (
            ("github-pat", "generic-api-key")
            if rule_first == "github-pat"
            else ("generic-api-key", "github-pat")
        )
        return [rf(rule_id=first, **common), rf(rule_id=second, **common)]

    def build(order: str) -> ScanCoordinator:
        registry = ScannerRegistry()
        registry.register(FakeScanner(findings(order), scanner_name="gitleaks"))
        return ScanCoordinator(default_config, registry)

    run_a = await build("generic-first").scan(["a.py"], mode="file")
    run_b = await build("github-first").scan(["a.py"], mode="file")
    assert run_a.total == run_b.total == 1
    assert run_a.findings[0].fingerprint == run_b.findings[0].fingerprint
    assert run_a.findings[0].rule_id == "github-pat"
    assert run_b.findings[0].rule_id == "github-pat"


@pytest.mark.asyncio
async def test_scan_keeps_all_cves_from_single_lockfile(default_config):
    """Регрессия T13: все CVE Trivy в requirements.txt (line_start=1 у всех,
    без сниппета) видны как отдельные находки, а не схлопываются в top-1."""
    cves = [
        rf(
            scanner="trivy",
            rule_id=f"CVE-{i}",
            raw_severity="high",
            file_path="requirements.txt",
            line_start=1,
            snippet="",
            category=Category.SCA,
        )
        for i in range(19)
    ]
    registry = ScannerRegistry()
    registry.register(FakeScanner(cves, scanner_name="trivy"))
    coord = ScanCoordinator(default_config, registry)
    result = await coord.scan(["requirements.txt"], mode="file")
    assert result.total == 19
    assert {f.rule_id for f in result.findings} == {f"CVE-{i}" for i in range(19)}


@pytest.mark.asyncio
async def test_scan_negative_merge_marks_potentially_fixed(default_config, tmp_path):
    """Находка, не найденная в следующем скане → POTENTIALLY_FIXED (ADR-0005 §2.2).

    Scoped negative-merge по охвату файла; вне git-репозитория — по project_id
    с предупреждением в meta.warnings (К10).
    """
    from appsecgate_mcp.storage.db import Database
    from appsecgate_mcp.storage.stores import ShownFindingsStore

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    db = Database(tmp_path / "shown.db")
    db.connect()
    shown = ShownFindingsStore(db, "pid-1")
    shown.init_schema()

    registry = ScannerRegistry()
    registry.register(FakeScanner([rf(file_path="a.py", snippet="x = 1")], scanner_name="fake"))
    coord = ScanCoordinator(
        default_config, registry, shown_store=shown, project_id="pid-1", project_root=str(tmp_path)
    )
    first = await coord.scan(["a.py"], mode="file")
    assert first.total == 1

    registry2 = ScannerRegistry()
    registry2.register(FakeScanner([], scanner_name="fake"))
    coord2 = ScanCoordinator(
        default_config, registry2, shown_store=shown, project_id="pid-1", project_root=str(tmp_path)
    )
    second = await coord2.scan(["a.py"], mode="file")
    assert second.total == 0

    rows = await shown.get_all(limit=10)
    assert rows and rows[0]["status"] == "POTENTIALLY_FIXED"
    assert rows[0]["missed_scan_count"] == 1
    assert any("negative-merge" in w for w in second.meta.warnings)
    db.close()
