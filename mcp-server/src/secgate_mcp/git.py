"""Git-интеграция через subprocess (без gitpython).

Для diff-режима MCP-серверу нужно получать списки изменённых файлов
(staged + unstaged + untracked) и содержимое diff. Всё делаем через `git` CLI
без shell (`shell=False`), без gitpython.
"""

from __future__ import annotations

from pathlib import Path

from secgate_mcp.scanners.runner import ScannerExecutionError, run_subprocess


class GitError(RuntimeError):
    """Ошибка взаимодействия с git."""


async def _git_name_only_z(cmd: list[str], cwd: str | Path | None) -> list[str]:
    """Запускает git-команду с `-z` и разбивает NUL-separated вывод на пути."""
    result = await run_subprocess(cmd, cwd=cwd)
    if result.returncode != 0:
        raise GitError(f"git command failed: {result.stderr.strip()}")
    return [p for p in result.stdout.split("\x00") if p]


async def git_changed_files(
    cwd: str | Path | None = None,
    *,
    untracked: bool = True,
) -> list[str]:
    """Возвращает отсортированный список изменённых файлов.

    Объединяет staged (`git diff --cached`), unstaged (`git diff`) и
    (опционально) untracked (`git ls-files --others`) пути. Дубликаты
    схлопываются через set; результат отсортирован для детерминизма.
    """
    paths: set[str] = set()
    paths.update(
        await _git_name_only_z(["git", "diff", "--cached", "--name-only", "-z"], cwd)
    )
    paths.update(await _git_name_only_z(["git", "diff", "--name-only", "-z"], cwd))
    if untracked:
        paths.update(
            await _git_name_only_z(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd
            )
        )
    return sorted(paths)


async def git_diff(
    cwd: str | Path | None = None,
    *,
    staged: bool = False,
    paths: list[str] | None = None,
) -> str:
    """Возвращает unified diff (unstaged по умолчанию, `--cached` при staged)."""
    cmd = ["git", "diff", "--no-ext-diff"]
    if staged:
        cmd.append("--cached")
    if paths:
        cmd.append("--")
        cmd.extend(paths)
    result = await run_subprocess(cmd, cwd=cwd)
    if result.returncode != 0:
        raise GitError(f"git diff failed: {result.stderr}")
    return result.stdout


async def git_tracked_files(
    cwd: str | Path | None = None,
) -> list[str]:
    """Возвращает список всех файлов, отслеживаемых git.
    """
    result = await run_subprocess(
        ["git", "ls-files", "--cached", "-z"], cwd=cwd
    )
    if result.returncode != 0:
        raise GitError(f"git ls-files failed: {result.stderr}")
    return [_ for _ in result.stdout.split("\x00") if _]


async def is_git_repo(cwd: str | Path | None = None) -> bool:
    """Проверяет, находится ли cwd внутри git-репозитория."""
    try:
        result = await run_subprocess(["git", "rev-parse", "--git-dir"], cwd=cwd)
    except ScannerExecutionError:
        return False
    return result.returncode == 0
