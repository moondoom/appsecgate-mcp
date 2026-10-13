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
