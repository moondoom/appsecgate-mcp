"""Относительные пути в координаторе: абсолютные пути сканеров не должны
влиять на file_path и fingerprint (локально, Docker, CI дают одинаковый результат)."""

from __future__ import annotations

import pytest

from appsecgate_mcp.models.finding import Category
from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.registry import ScannerRegistry


class _AbsPathScanner(BaseScanner):
    name = "fake"

    def __init__(self, findings, **kw):
        super().__init__(**kw)
        self._findings = findings

    async def is_available(self) -> bool:
        return True

    async def scan(self, files, mode):
        return list(self._findings)


def _rf(file_path: str) -> RawFinding:
    return RawFinding(
        rule_id="r",
        raw_severity="high",
        file_path=file_path,
        scanner="fake",
        snippet="password = 'x'",
        category=Category.SECRET,
    )


def _coord(config, findings, project_root: str) -> ScanCoordinator:
    registry = ScannerRegistry()
    registry.register(_AbsPathScanner(findings))
    return ScanCoordinator(config, registry, project_root=project_root)


@pytest.mark.asyncio
async def test_absolute_path_becomes_relative(default_config, tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    coord = _coord(default_config, [_rf(str(root / "src" / "a.py"))], str(root))

    result = await coord.scan(["src/a.py"], mode="file")

    assert result.total == 1
    assert result.findings[0].file_path == "src/a.py"


@pytest.mark.asyncio
async def test_same_file_gives_same_fingerprint_across_mount_points(default_config, tmp_path):
    local_root = tmp_path / "local"
    docker_root = tmp_path / "docker_mount"
    for root in (local_root, docker_root):
        (root / "src").mkdir(parents=True)

    local = _coord(default_config, [_rf(str(local_root / "src" / "a.py"))], str(local_root))
    docker = _coord(default_config, [_rf(str(docker_root / "src" / "a.py"))], str(docker_root))

    local_result = await local.scan(["src/a.py"], mode="file")
    docker_result = await docker.scan(["src/a.py"], mode="file")

    assert local_result.findings[0].fingerprint == docker_result.findings[0].fingerprint
    assert local_result.findings[0].file_path == docker_result.findings[0].file_path


@pytest.mark.asyncio
async def test_path_outside_project_excluded_with_warning(default_config, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "other" / "secret.py"
    coord = _coord(default_config, [_rf(str(outside))], str(root))

    result = await coord.scan(["src/a.py"], mode="file")

    assert result.total == 0
    assert any("outside project root" in w for w in result.meta.warnings)


@pytest.mark.asyncio
async def test_relative_input_unchanged_without_project_root(default_config):
    registry = ScannerRegistry()
    registry.register(_AbsPathScanner([_rf("a.py")]))
    coord = ScanCoordinator(default_config, registry)

    result = await coord.scan(["a.py"], mode="file")

    assert result.total == 1
    assert result.findings[0].file_path == "a.py"
