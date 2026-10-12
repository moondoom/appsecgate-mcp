"""meta.scanned_files: абсолютные пути внутри проекта становятся относительными,
пути вне проекта исключаются, без project_root координатор не падает."""

from __future__ import annotations

import pytest

from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.scanners.base import BaseScanner
from appsecgate_mcp.scanners.registry import ScannerRegistry


class _NoopScanner(BaseScanner):
    name = "fake"

    async def is_available(self) -> bool:
        return True

    async def scan(self, files, mode):
        return []


def _coord(config, project_root: str | None) -> ScanCoordinator:
    registry = ScannerRegistry()
    registry.register(_NoopScanner())
    return ScanCoordinator(config, registry, project_root=project_root)


@pytest.mark.asyncio
async def test_absolute_inside_project_becomes_relative(default_config, tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    coord = _coord(default_config, str(root))

    result = await coord.scan([str(root / "src" / "a.py")], mode="file")

    assert result.meta.scanned_files == ["src/a.py"]


@pytest.mark.asyncio
async def test_relative_input_kept_relative(default_config, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    coord = _coord(default_config, str(root))

    result = await coord.scan(["src/./a.py"], mode="file")

    assert result.meta.scanned_files == ["src/a.py"]


@pytest.mark.asyncio
async def test_path_outside_project_excluded_from_scanned_files(default_config, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "other" / "x.py"
    coord = _coord(default_config, str(root))

    result = await coord.scan([str(outside), "src/a.py"], mode="file")

    assert result.meta.scanned_files == ["src/a.py"]
    assert any("outside project root" in w for w in result.meta.warnings)


@pytest.mark.asyncio
async def test_no_project_root_does_not_raise(default_config, tmp_path):
    coord = _coord(default_config, None)
    absolute = str(tmp_path / "a.py")

    result = await coord.scan([absolute, "b.py"], mode="file")

    assert result.meta.scanned_files == [absolute, "b.py"]
