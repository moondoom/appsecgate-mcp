"""CLI-подкоманда `appsecgate-mcp ci` (Фаза 2, ADR-0003).

Запускает CI-оценку diff проекта против base-ветки и печатает результат:
text — человекочитаемая сводка, ndjson — построчный JSON для пайплайнов.
Exit code: 0 = pass, 1 = blocked, 2 = инфраструктурная ошибка.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from appsecgate_mcp.logging_setup import configure_logging
from appsecgate_mcp.models.finding import Finding, ScanResult
from appsecgate_mcp.orchestration.ci import CiResult, run_ci
from appsecgate_mcp.orchestration.gate import GateDecision, GateSummary

logger = logging.getLogger(__name__)

# Стандартное место snapshot (ADR-0003 §6.1); можно перекрыть --shown-snapshot.
_SNAPSHOT_FILE = ".appsecgate-mcp/shown.ndjson"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="appsecgate-mcp ci",
        description="CI-оценка diff по gates (Фаза 2, ADR-0003)",
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("APPSECGATE_PROJECT_PATH")
        or os.environ.get("APPSECGATE_WORKSPACE")
        or ".",
        help="Корень проекта для сканирования",
    )
    parser.add_argument(
        "--base-ref",
        default=None,
        help=(
            "Базовая ветка для diff (`git diff <ref>...HEAD`). "
            "По умолчанию gates.ci.diff_base_ref (origin/main)."
        ),
    )
    parser.add_argument(
        "--shown-snapshot",
        default=None,
        help=f"Путь к snapshot показанного. По умолчанию <project>/{_SNAPSHOT_FILE}.",
    )
    parser.add_argument(
        "--require-shown-snapshot",
        action="store_true",
        help="Без валидного snapshot — exit 2 (fail-closed, вариант А ADR-0003)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "ndjson"],
        default="text",
        help="text — сводка; ndjson — построчный JSON для пайплайнов",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("APPSECGATE_LOG_LEVEL", "INFO"),
        help="Уровень логирования. По умолчанию INFO.",
    )
    parser.add_argument(
        "--log-file",
        default=os.environ.get("APPSECGATE_LOG_FILE"),
        help="Файл лога с ротацией. Без него логи пишутся только в stderr.",
    )
    return parser


def _decisions_index(summary: GateSummary) -> dict[str, GateDecision]:
    return {
        d.fingerprint: d
        for d in (*summary.blocked, *summary.warned, *summary.informed, *summary.skipped)
    }


def _findings_index(result: ScanResult) -> dict[str, Finding]:
    return {f.fingerprint: f for f in result.findings}


def _format_text(result: CiResult) -> str:
    if result.error:
        return f"appsecgate ci: error: {result.error}"
    assert result.summary is not None and result.result is not None
    summary = result.summary
    meta = result.result.meta
    lines = [
        "appsecgate ci: "
        f"scanned={len(meta.scanned_files)} scanners={','.join(meta.scanners_ran) or '-'}"
    ]
    for warning in result.warnings:
        lines.append(f"warning: {warning}")
    lines.append(
        f"total={summary.total} blocked={summary.block_count} "
        f"warned={len(summary.warned)} info={len(summary.informed)} "
        f"skipped={summary.skip_count}"
    )
    by_fp = _findings_index(result.result)
    for decision in summary.blocked:
        finding = by_fp.get(decision.fingerprint)
        if finding is not None:
            loc = f"{finding.file_path}:{finding.line_start}"
            lines.append(
                f"BLOCK [{decision.reason}] {finding.severity.value} {finding.rule_id} {loc}"
            )
        else:
            lines.append(f"BLOCK [{decision.reason}] ({decision.fingerprint})")
    lines.append("result: blocked" if summary.should_fail else "result: pass")
    return "\n".join(lines)


def _finding_json(finding: Finding, decision: GateDecision | None) -> dict:
    return {
        "type": "finding",
        "fp": finding.fingerprint,
        "rule_id": finding.rule_id,
        "file": finding.file_path,
        "line_start": finding.line_start,
        "line_end": finding.line_end,
        "severity": finding.severity.value,
        "scanner": finding.scanner,
        "category": finding.category.value,
        "decision": decision.action if decision else "info",
        "reason": decision.reason if decision else "ci_info",
    }


def _format_ndjson(result: CiResult) -> str:
    if result.error:
        return json.dumps({"type": "error", "error": result.error}, ensure_ascii=False)
    assert result.summary is not None and result.result is not None
    summary = result.summary
    meta = result.result.meta
    header = {
        "type": "summary",
        "mode": "ci",
        "total": summary.total,
        "blocked": summary.block_count,
        "warned": len(summary.warned),
        "info": len(summary.informed),
        "skipped": summary.skip_count,
        "by_reason": summary.by_reason,
        "should_fail": summary.should_fail,
        "scanned_files": meta.scanned_files,
        "scanners_ran": meta.scanners_ran,
        "warnings": result.warnings,
    }
    lines = [json.dumps(header, ensure_ascii=False)]
    decisions = _decisions_index(summary)
    for finding in result.result.findings:
        lines.append(
            json.dumps(
                _finding_json(finding, decisions.get(finding.fingerprint)), ensure_ascii=False
            )
        )
    return "\n".join(lines)


def ci_main(argv: list[str], *, registry=None) -> int:
    """Точка входа `appsecgate-mcp ci <args>`; возвращает exit code.

    ``registry`` — инъекция реестра сканеров (тесты); None — из конфига.
    """
    args = _build_parser().parse_args(argv)
    configure_logging(args.log_level, args.log_file)
    logger.info("ci start project=%s", args.project)

    snapshot = args.shown_snapshot or str(Path(args.project).resolve() / _SNAPSHOT_FILE)
    # Флаг CLI перекрывает конфиг; без флага решает gates.ci.require_shown_snapshot.
    require_snapshot = args.require_shown_snapshot or None
    result = asyncio.run(
        run_ci(
            project_path=args.project,
            base_ref=args.base_ref,
            shown_snapshot=snapshot,
            require_shown_snapshot=require_snapshot,
            registry=registry,
        )
    )

    if args.format == "ndjson":
        sys.stdout.write(_format_ndjson(result) + "\n")
    else:
        sys.stdout.write(_format_text(result) + "\n")
    logger.info("ci done exit=%s", result.exit_code)
    return result.exit_code
