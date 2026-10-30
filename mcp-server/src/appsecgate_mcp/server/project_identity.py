"""Проектная идентичность: ``project_id`` / ``project_alias`` (T9).

Приоритет ``_resolve_project_identity``:
1. явный ``project_id`` (``APPSECGATE_PROJECT_ID`` / ``--project-id``) — как есть;
2. явный alias (``APPSECGATE_PROJECT_ALIAS`` / ``--project-alias``) —
   ``project_id = sha256('alias:' + alias)[:16]``;
3. имя git-репозитория (``origin`` URL или имя каталога ``.git``) —
   ``project_id = sha256('git:' + имя)[:16]``;
4. фолбэк: ``sha256(realpath(project_path))[:16]`` (прежнее поведение).
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def _compute_project_id(project_path: str) -> str:
    """Стабильная проектная идентичность: ``sha256(realpath(project_path))[:16]``.

    Проект определяется физическим путём (симлинки раскрываются через
    ``resolve()``), поэтому два разных представления одного и того же каталога
    дают одинаковый ``project_id``. Это фолбэк ``_resolve_project_identity``.
    """
    return hashlib.sha256(str(Path(project_path).resolve()).encode()).hexdigest()[:16]


def _find_git_dir(start: Path) -> Path | None:
    """Ищет ``.git`` (каталог или файл worktree) вверх по дереву от ``start``."""
    current = start
    while True:
        candidate = current / ".git"
        if candidate.exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def _repo_name_from_git_url(url: str) -> str:
    """Имя репозитория из ``origin`` URL: последний компонент пути без ``.git``."""
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    name = cleaned.split("/")[-1] if "/" in cleaned else cleaned
    if ":" in name:
        # scp-style: git@host:org/repo → имя после последнего ':'
        name = name.split(":")[-1]
    return name


def _git_identity(project_path: str) -> str | None:
    """Детерминированное имя git-репозитория проекта (для project_id, T9).

    Берём имя ``origin`` remote из ``.git/config`` (последний компонент URL),
    иначе — имя каталога, содержащего ``.git``. В Docker с bind-mount
    ``.:/workspace:ro`` это даёт ``project_id`` от host-репозитория, а не от
    контейнерного пути ``/workspace``.
    """
    root = Path(project_path).resolve()
    git_dir = _find_git_dir(root)
    if git_dir is None:
        return None
    if git_dir.is_file():
        # linked worktree: .git — файл с gitdir-указателем, имя — каталог работы.
        return git_dir.parent.name
    config_file = git_dir / "config"
    if config_file.is_file():
        for line in config_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.lower().startswith("url ="):
                name = _repo_name_from_git_url(line.split("=", 1)[1])
                if name:
                    return name
    return git_dir.parent.name


def _resolve_project_identity(
    project_path: str,
    *,
    explicit_id: str | None = None,
    explicit_alias: str | None = None,
) -> tuple[str, str]:
    """Возвращает ``(project_id, project_alias)`` с приоритетом (T9):

    1. явный ``project_id`` (``APPSECGATE_PROJECT_ID`` / ``--project-id``) — как есть;
    2. явный alias (``APPSECGATE_PROJECT_ALIAS`` / ``--project-alias``) —
       ``project_id = sha256('alias:' + alias)[:16]``;
    3. имя git-репозитория — ``project_id = sha256('git:' + имя)[:16]``;
    4. фолбэк: ``sha256(realpath(project_path))[:16]`` (прежнее поведение).
    """
    resolved = str(Path(project_path).resolve())
    if explicit_id and explicit_id.strip():
        return explicit_id.strip(), (explicit_alias or Path(resolved).name).strip()
    if explicit_alias and explicit_alias.strip():
        alias = explicit_alias.strip()
        return hashlib.sha256(f"alias:{alias}".encode()).hexdigest()[:16], alias
    git_name = _git_identity(resolved)
    if git_name:
        return hashlib.sha256(f"git:{git_name}".encode()).hexdigest()[:16], git_name
    return _compute_project_id(resolved), Path(resolved).name
