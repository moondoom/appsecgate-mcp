"""Нормализация путей сканеров: вид относительно корня проекта."""

from __future__ import annotations

from appsecgate_mcp.scanners.base import BaseScanner


class _StubScanner(BaseScanner):
    name = "stub"

    async def scan(self, files, mode):
        return []

    async def is_available(self) -> bool:
        return True


def test_dotdir_prefix_is_preserved(tmp_path):
    scanner = _StubScanner(project_path=str(tmp_path))
    assert scanner.normalize_path(".github/workflows/ci.yml") == ".github/workflows/ci.yml"


def test_absolute_path_inside_project_becomes_relative(tmp_path):
    scanner = _StubScanner(project_path=str(tmp_path))
    absolute = str(tmp_path / "src" / "a.py")
    assert scanner.normalize_path(absolute) == "src/a.py"


def test_dot_slash_prefix_is_stripped(tmp_path):
    scanner = _StubScanner(project_path=str(tmp_path))
    assert scanner.normalize_path("./src/a.py") == "src/a.py"


def test_absolute_dotdir_inside_project(tmp_path):
    scanner = _StubScanner(project_path=str(tmp_path))
    absolute = str(tmp_path / ".github" / "workflows" / "ci.yml")
    assert scanner.normalize_path(absolute) == ".github/workflows/ci.yml"


def test_path_outside_project_is_not_relativized(tmp_path):
    scanner = _StubScanner(project_path=str(tmp_path))
    outside = str(tmp_path.parent / "other.py")
    assert scanner.normalize_path(outside) == outside


def test_empty_path(tmp_path):
    scanner = _StubScanner(project_path=str(tmp_path))
    assert scanner.normalize_path("") == ""
