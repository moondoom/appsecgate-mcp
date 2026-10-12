"""Тесты выбора целей Semgrep в project-режиме (без запуска semgrep)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from appsecgate_mcp.scanners.semgrep import SemgrepAdapter


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _relative(paths: list[str], root: Path) -> list[str]:
    return sorted(Path(p).relative_to(root).as_posix() for p in paths)


@pytest.mark.skipif(not _git_available(), reason="git недоступен")
class TestGitEnumeration:
    async def test_respects_gitignore_and_supported_extensions(self, tmp_path: Path):
        _git_init(tmp_path)
        _write(tmp_path / ".gitignore", "ignored/\n")
        _write(tmp_path / "src" / "app.py")
        _write(tmp_path / "notes.txt")
        _write(tmp_path / "ignored" / "secret.py")

        adapter = SemgrepAdapter(project_path=str(tmp_path))
        result = await adapter._enumerate_project(["."])

        assert _relative(result, tmp_path) == ["src/app.py"]

    async def test_includes_untracked_files(self, tmp_path: Path):
        _git_init(tmp_path)
        _write(tmp_path / "new_module.py")

        adapter = SemgrepAdapter(project_path=str(tmp_path))
        result = await adapter._git_listed_files(tmp_path)

        assert result is not None
        assert _relative(result, tmp_path) == ["new_module.py"]

    async def test_non_git_directory_returns_none(self, tmp_path: Path):
        _write(tmp_path / "app.py")

        adapter = SemgrepAdapter(project_path=str(tmp_path))
        assert await adapter._git_listed_files(tmp_path) is None


class TestRglobFallback:
    async def test_falls_back_to_rglob_when_git_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        _write(tmp_path / "pkg" / "mod.py")
        _write(tmp_path / "README.md")

        adapter = SemgrepAdapter(project_path=str(tmp_path))

        async def _no_git(root: Path) -> None:
            return None

        monkeypatch.setattr(adapter, "_git_listed_files", _no_git)
        result = await adapter._enumerate_project(["."])

        assert _relative(result, tmp_path) == ["pkg/mod.py"]


class TestSingleFileProject:
    async def test_supported_file_is_returned(self, tmp_path: Path):
        target = tmp_path / "app.py"
        _write(target)

        adapter = SemgrepAdapter(project_path=str(tmp_path))
        assert await adapter._enumerate_project([str(target)]) == [str(target)]

    async def test_unsupported_file_is_skipped(self, tmp_path: Path):
        target = tmp_path / "notes.txt"
        _write(target)

        adapter = SemgrepAdapter(project_path=str(tmp_path))
        assert await adapter._enumerate_project([str(target)]) == []


class TestSelectTargets:
    async def test_project_mode_delegates_to_enumeration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        adapter = SemgrepAdapter(project_path=str(tmp_path))
        calls: list[list[str]] = []

        async def _fake_enumerate(files: list[str]) -> list[str]:
            calls.append(files)
            return ["enumerated.py"]

        monkeypatch.setattr(adapter, "_enumerate_project", _fake_enumerate)
        result = await adapter._select_targets(["."], "project")

        assert result == ["enumerated.py"]
        assert calls == [["."]]

    async def test_file_mode_filters_by_extension(self, tmp_path: Path):
        adapter = SemgrepAdapter(project_path=str(tmp_path))
        files = ["a.py", "b.txt", "c.go"]

        result = await adapter._select_targets(files, "file")

        assert result == ["a.py", "c.go"]
