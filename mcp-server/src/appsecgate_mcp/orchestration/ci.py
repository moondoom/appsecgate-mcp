"""CI-режим (Фаза 2, ADR-0003): блокировка по severity и unresolved_local.

Отдельный процесс, не MCP-тул: `appsecgate-mcp ci` запускается из workflow
без доступа к локальному shown_findings.db. Вход — diff против base-ветки,
опциональный snapshot показанного (пишет агент). Выход — exit code:
0 = pass, 1 = blocked, 2 = ошибка инфраструктуры (git/конфиг/сканеры).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from appsecgate_mcp.config.loader import ConfigLoader
from appsecgate_mcp.git import GitError, git_changed_files_vs_base
from appsecgate_mcp.models.finding import ScanResult
from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.orchestration.gate import GateEngine, GateSummary
from appsecgate_mcp.orchestration.shown_source import (
    ShownSnapshotError,
    SnapshotShownSource,
    parse_shown_snapshot,
)
from appsecgate_mcp.scanners.registry import ScannerRegistry

logger = logging.getLogger(__name__)

EXIT_PASS = 0
EXIT_BLOCKED = 1
EXIT_INFRA = 2


@dataclass
class CiResult:
    """Итог CI-оценки: exit_code + данные для текстового/ndjson-вывода."""

    exit_code: int
    summary: GateSummary | None = None
    result: ScanResult | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _load_shown_source(
    shown_snapshot: str | None,
    *,
    require: bool,
    warnings: list[str],
) -> tuple[SnapshotShownSource | None, str | None]:
    """Парсит snapshot (если передан) в источник показанного (ADR-0003 §5.3).

    Snapshot опционален (вариант В): при отсутствии/битости — warning +
    ``None`` (severity-only), если не включён ``require`` (тогда exit 2).
    Возвращает ``(source, error)``: error непуст только при fail-closed.
    """
    if not shown_snapshot:
        return None, None
    path = Path(shown_snapshot)
    if not path.is_file():
        message = f"shown snapshot not found: {shown_snapshot}"
        if require:
            return None, message
        warnings.append(f"{message} — unresolved_local disabled, severity-gate only")
        return None, None
    try:
        snapshot = parse_shown_snapshot(path)
    except (ShownSnapshotError, OSError) as exc:
        message = f"invalid shown snapshot {shown_snapshot}: {exc}"
        if require:
            return None, message
        warnings.append(f"{message} — unresolved_local disabled, severity-gate only")
        return None, None
    if snapshot.expired_count:
        warnings.append(f"ignored {snapshot.expired_count} expired shown record(s) (retention)")
    return SnapshotShownSource(snapshot), None


async def run_ci(
    *,
    project_path: str,
    base_ref: str | None = None,
    shown_snapshot: str | None = None,
    require_shown_snapshot: bool = False,
    registry: ScannerRegistry | None = None,
) -> CiResult:
    """Оценивает diff проекта против ``base_ref`` по CI-правилам.

    ``registry`` — инъекция для тестов; по умолчанию собирается из конфига.
    Ничего не пишет: ``persist=False``, snapshot только читается (:ro).
    """
    project = Path(project_path).resolve()
    if not project.is_dir():
        return CiResult(exit_code=EXIT_INFRA, error=f"project not found: {project_path}")

    try:
        config = ConfigLoader().load(project)
    except Exception as exc:  # noqa: BLE001 — битый конфиг = «CI сломан», exit 2
        return CiResult(exit_code=EXIT_INFRA, error=f"invalid config: {exc}")

    reg = registry or ScannerRegistry.from_config(config, project_path=str(project))
    if not reg.all():
        return CiResult(exit_code=EXIT_INFRA, error="no scanners configured (all disabled?)")
    available = [scanner for scanner in reg.all() if await scanner.is_available()]
    if not available:
        return CiResult(
            exit_code=EXIT_INFRA,
            error="no scanners available (binaries missing?) — CI cannot run",
        )

    base = base_ref or config.gates.ci.diff_base_ref
    try:
        files = await git_changed_files_vs_base(project, base)
    except GitError as exc:
        return CiResult(
            exit_code=EXIT_INFRA,
            error=f"git error (base-ref {base!r}): {exc}",
        )

    warnings: list[str] = []
    shown_source, fail = _load_shown_source(
        shown_snapshot,
        require=require_shown_snapshot,
        warnings=warnings,
    )
    if fail:
        return CiResult(exit_code=EXIT_INFRA, error=fail)

    coordinator = ScanCoordinator(config, reg, project_root=str(project))
    result = await coordinator.scan(files, mode="diff", persist=False)

    gate = GateEngine(config, shown_store=shown_source)
    summary = await gate.evaluate_all(result.findings, mode="ci")

    warnings.extend(result.meta.warnings)
    for err in result.meta.errors:
        warnings.append(f"scanner error {err.scanner}: {err.error}")
    warnings.extend(config.rules_warnings or [])

    exit_code = EXIT_BLOCKED if summary.should_fail else EXIT_PASS
    logger.info(
        "ci done exit=%s total=%s blocked=%s warnings=%s",
        exit_code,
        summary.total,
        summary.block_count,
        len(warnings),
    )
    return CiResult(exit_code=exit_code, summary=summary, result=result, warnings=warnings)
