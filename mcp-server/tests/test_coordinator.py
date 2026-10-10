"""Тесты ScanCoordinator с фейковым сканером (без бинарников)."""

from __future__ import annotations

import pytest

from secgate_mcp.models.finding import Category
from secgate_mcp.orchestration.coordinator import ScanCoordinator
from secgate_mcp.scanners.base import BaseScanner, RawFinding
from secgate_mcp.scanners.registry import ScannerRegistry


class FakeScanner(BaseScanner):
    name = "fake"

    def __init__(self, findings, *, available=True, boom=False, **kw):
        super().__init__(**kw)
        self._findings = findings
        self._available = available
        self._boom = boom

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
