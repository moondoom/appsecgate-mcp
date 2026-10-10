"""Тесты git-интеграции на реальном временном репозитории."""

from __future__ import annotations

import subprocess

import pytest

from appsecgate_mcp.git import (
    GitError,
    git_changed_files,
    git_diff,
    is_git_repo,
)

pytestmark = pytest.mark.asyncio


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    return root


async def test_is_git_repo(repo, tmp_path):
    assert await is_git_repo(repo) is True
    other = tmp_path / "nope"
    other.mkdir()
    assert await is_git_repo(other) is False


async def test_changed_files_untracked_and_modified(repo):
    (repo / "tracked.py").write_text("a = 1\n")
    _git(repo, "add", "tracked.py")
    _git(repo, "commit", "-m", "init")

    (repo / "tracked.py").write_text("a = 2\n")  # unstaged modification
    (repo / "new.py").write_text("b = 1\n")  # untracked

    files = await git_changed_files(repo)
    assert "tracked.py" in files
    assert "new.py" in files
    assert files == sorted(files)


async def test_git_diff(repo):
    (repo / "f.py").write_text("a = 1\n")
    _git(repo, "add", "f.py")
    _git(repo, "commit", "-m", "init")
    (repo / "f.py").write_text("a = 2\n")
    diff = await git_diff(repo)
    assert "-a = 1" in diff
    assert "+a = 2" in diff


async def test_git_error_outside_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(GitError):
        await git_changed_files(plain)
