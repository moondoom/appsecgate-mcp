"""CI-режим (Фаза 2, ADR-0004 MS-6): блокировка по severity и unresolved_local.

Отдельный процесс, не MCP-тул: `appsecgate-mcp ci` запускается из workflow.
Вход — diff против base-ветки, «показанное» — всегда с master (`GET
/v1/findings`, единственный канал; snapshot удалён решением владельца
2026-10-31). Выход — exit code: 0 = pass, 1 = blocked,
2 = ошибка инфраструктуры (git/конфиг/сканеры/master).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from appsecgate_mcp.config.loader import ConfigLoader
from appsecgate_mcp.git import GitError, git_changed_files_vs_base, git_current_branch
from appsecgate_mcp.models.finding import ScanResult
from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.orchestration.gate import GateEngine, GateSummary
from appsecgate_mcp.orchestration.shown_source import (
    MasterFindingsError,
    MasterShownSource,
    fetch_findings,
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


async def run_ci(
    *,
    project_path: str,
    base_ref: str | None = None,
    master_url: str | None = None,
    master_api_key: str = "",
    project_id: str | None = None,
    master_timeout: float = 30,
    registry: ScannerRegistry | None = None,
) -> CiResult:
    """Оценивает diff проекта против ``base_ref`` по CI-правилам.

    ``registry`` — инъекция для тестов; по умолчанию собирается из конфига.
    Ничего не пишет: ``persist=False``, master только читается.
    CI fail-closed: без master (или при его ошибке) — exit 2 (ADR-0004 §6).
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

    # Текущая ветка CI для skip-if-same-branch (ADR-0006 §2.3). Не
    # определяется → None → WONT_FIX на «своей» ветке не распознаётся и
    # консервативно блокирует (правило `<unknown>`).
    try:
        branch = await git_current_branch(project)
    except GitError:
        branch = None

    # MS-6: «показанное» — всегда master, без него CI не запускается.
    if not master_url:
        return CiResult(
            exit_code=EXIT_INFRA,
            error="ci requires master (--master-url / APPSECGATE_MASTER_URL)",
        )
    if not project_id:
        return CiResult(
            exit_code=EXIT_INFRA,
            error="ci requires project id (--project-id / APPSECGATE_PROJECT_ID)",
        )
    try:
        records = fetch_findings(
            master_url,
            project_id,
            master_api_key,
            timeout=master_timeout,
        )
    except MasterFindingsError as exc:
        return CiResult(exit_code=EXIT_INFRA, error=str(exc))
    shown_source = MasterShownSource(records)

    warnings: list[str] = []
    coordinator = ScanCoordinator(config, reg, project_root=str(project))
    result = await coordinator.scan(files, mode="diff", persist=False)

    gate = GateEngine(config, shown_store=shown_source, branch=branch)
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
