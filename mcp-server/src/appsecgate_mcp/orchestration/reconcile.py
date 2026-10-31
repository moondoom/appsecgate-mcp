"""Reconciliation-хелперы скана (ADR-0005 §2.1–2.4).

Положительный merge выполняется в store (``record_shown_batch``); здесь —
git-контекст (ветка/коммит) и scoped negative-merge (не найдено в охвате →
``POTENTIALLY_FIXED``).
"""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.git import GitError, git_current_branch, git_current_commit
from appsecgate_mcp.models.finding import ScanMeta
from appsecgate_mcp.scanners.runner import ScannerExecutionError

UNKNOWN_BRANCH = "<unknown>"


async def git_context(project_root: str | None) -> tuple[str, str | None, bool]:
    """Возвращает ``(branch, commit, git_ok)`` текущего HEAD (ADR-0005 §2.4).

    Вне git-репозитория — ``("<unknown>", None, False)``: negative-merge
    по ``project_id`` с предупреждением (К10).
    """
    if project_root is None:
        return UNKNOWN_BRANCH, None, False
    try:
        branch = await git_current_branch(project_root)
    except (GitError, ScannerExecutionError):
        return UNKNOWN_BRANCH, None, False
    try:
        commit = await git_current_commit(project_root)
    except (GitError, ScannerExecutionError):
        commit = None
    return branch, commit, True


async def negative_merge(
    shown_store: Any,
    *,
    project_id: str,
    scope_files: list[str],
    scanned_set: set[str],
    found_fingerprints: set[str],
    branch: str,
    git_ok: bool,
    meta: ScanMeta,
    global_scope: bool = False,
) -> None:
    """Negative-merge (ADR-0005 §2.1–2.2): не найденное в охвате → POTENTIALLY_FIXED.

    Переходы выполняются только для находок в охвате тула и той же ветки
    (§2.4); при ``branch="<unknown>"`` — по ``project_id`` с предупреждением
    (К10). ``FIXED``/``SUPPRESSED``/``WONT_FIX`` не трогаются (К7);
    deleted-файлы (в охвате, но не отсканированы) переводят активные
    статусы с ``missed_scan_count=1``.

    ``global_scope=True`` (scan_project, §2.1) — охват = весь проект/ветка:
    файловый фильтр не применяется, negative-merge глобальный.
    """
    if not project_id or (not global_scope and not scope_files):
        return
    if not git_ok:
        meta.warnings.append(
            "git context unavailable: branch='<unknown>', negative-merge by project_id only"
        )
    try:
        candidates = await shown_store.get_negative_candidates(
            project_id, None if global_scope else scope_files, branch
        )
    except Exception as exc:
        meta.warnings.append(f"negative-merge failed: {exc}")
        return
    if not candidates:
        return

    deleted_files = set() if global_scope else {fp for fp in scope_files if fp not in scanned_set}
    updates: list[tuple[str, str, int]] = []
    for cand in candidates:
        fp = cand["fingerprint"]
        if fp in found_fingerprints:
            continue
        status = cand["status"]
        if status in ("FIXED", "SUPPRESSED", "WONT_FIX"):
            continue  # К7: не трогаем
        if cand["file_path"] in deleted_files:
            updates.append((fp, "POTENTIALLY_FIXED", 1))
        elif status == "POTENTIALLY_FIXED":
            updates.append((fp, "POTENTIALLY_FIXED", int(cand["missed_scan_count"]) + 1))
        else:  # SHOWN, REOPENED
            updates.append((fp, "POTENTIALLY_FIXED", 1))
    if not updates:
        return
    try:
        await shown_store.mark_missing(updates)
    except Exception as exc:
        meta.warnings.append(f"negative-merge write failed: {exc}")
