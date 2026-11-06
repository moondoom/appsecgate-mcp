"""CLI-подкоманда `appsecgate-mcp sync` (MS-3/MS-5, ADR-0004 §4.2).

Запускается НА ХОСТЕ, вне read-only/no-network контейнера MCP-сервера
(инвариант №2 не затрагивается). Пушит локальные события через durable outbox,
затем скачивает CI/global suppressions и центральную policy в локальный data-dir.

Exit code: 0 = ok (push/pull завершены или `--dry-run`),
1 = push или pull частично не удался (retry следующим запуском),
2 = инфраструктурная ошибка (нет БД, project-id, --master-url, битая схема).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from appsecgate_mcp.logging_setup import configure_logging
from appsecgate_mcp.sync.export import ExportError, ExportResult, export_events
from appsecgate_mcp.sync.outbox import Outbox
from appsecgate_mcp.sync.pull import PullError, pull_master
from appsecgate_mcp.sync.push import push_outbox
from appsecgate_mcp.sync.triage import append_triage_events

logger = logging.getLogger(__name__)

# ADR-0004 §4.2: очередь неотправленного живёт в ~/.appsecgate/sync/outbox.ndjson.
DEFAULT_OUTBOX = Path.home() / ".appsecgate" / "sync" / "outbox.ndjson"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="appsecgate-mcp sync",
        description="Экспорт локальных БД → события master + идемпотентный push (MS-3)",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("APPSECGATE_DATA_DIR")
        or os.environ.get("APPSECGATE_MCP_HOME")
        or str(Path.home() / ".appsecgate-mcp"),
        help="Каталог локальных БД, где лежит shown_findings.db",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Проект для push/pull; обязателен при нескольких проектах в БД",
    )
    parser.add_argument(
        "--outbox",
        default=os.environ.get("APPSECGATE_SYNC_OUTBOX") or str(DEFAULT_OUTBOX),
        help="Файл очереди неотправленного (NDJSON)",
    )
    parser.add_argument(
        "--master-url",
        default=os.environ.get("APPSECGATE_MASTER_URL"),
        help="Базовый URL master (например https://appsecgate.example.com)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("APPSECGATE_MASTER_API_KEY"),
        help="API-ключ проекта (Authorization: Bearer)",
    )
    parser.add_argument("--batch-size", type=int, default=200, help="Событий в одном HTTP-батче")
    parser.add_argument("--timeout", type=float, default=30, help="Таймаут HTTP-запроса, секунд")
    parser.add_argument(
        "--dry-run", action="store_true", help="Только экспорт, без outbox/HTTP/pull"
    )
    parser.add_argument(
        "--format",
        choices=["text", "ndjson"],
        default="text",
        help="text — сводка; ndjson — построчный вывод событий (в связке с --dry-run)",
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


def _print_export(exported: ExportResult, fmt: str) -> int:
    """Вывод результата экспорта в --dry-run (без записи outbox/push)."""
    if fmt == "ndjson":
        for event in exported.events:
            print(json.dumps(event, ensure_ascii=False, sort_keys=True))
        return 0
    lines = [
        "appsecgate sync: dry-run "
        f"projects={exported.project_count} findings={exported.finding_count} "
        f"events={len(exported.events)}"
    ]
    for event_type, count in sorted(exported.by_event.items()):
        lines.append(f"  {event_type}: {count}")
    print("\n".join(lines))
    return 0


def sync_main(argv: list[str] | None = None) -> int:
    """Точка входа: `appsecgate-mcp sync [flags]`."""
    args = _build_parser().parse_args(argv)
    configure_logging(args.log_level, args.log_file)

    db_path = Path(args.data_dir) / "shown_findings.db"
    if not db_path.is_file():
        print(f"appsecgate sync: error: shown_findings.db not found: {db_path}", file=sys.stderr)
        return 2
    try:
        exported = export_events(db_path, project_id=args.project_id)
    except ExportError as exc:
        print(f"appsecgate sync: error: {exc}", file=sys.stderr)
        return 2
    append_triage_events(exported, args.data_dir, args.project_id)

    if args.dry_run:
        return _print_export(exported, args.format)

    project_id = args.project_id or None
    project_ids = {event["project_key"] for event in exported.events if event.get("project_key")}
    if project_id is None and len(project_ids) == 1:
        project_id = next(iter(project_ids))
    if project_id is None and len(project_ids) > 1:
        print(
            "appsecgate sync: error: --project-id required for a multi-project database",
            file=sys.stderr,
        )
        return 2

    if not args.master_url:
        print(
            "appsecgate sync: error: --master-url required (или APPSECGATE_MASTER_URL)",
            file=sys.stderr,
        )
        return 2

    outbox = Outbox(args.outbox)
    appended = outbox.append(exported.events)
    result = push_outbox(
        outbox,
        args.master_url,
        args.api_key or "",
        batch_size=args.batch_size,
        timeout=args.timeout,
        project_id=project_id,
    )

    pull_error: PullError | None = None
    pull_summary = "pull=skipped"
    if project_id is not None:
        try:
            pulled = pull_master(
                args.master_url,
                project_id,
                args.api_key or "",
                args.data_dir,
                timeout=args.timeout,
            )
        except PullError as exc:
            pull_error = exc
            pull_summary = "pull_failed=1"
        else:
            policy = "applied" if pulled.policy_present else "absent"
            pull_summary = (
                f"pulled_suppressions={pulled.suppression_count} policy={policy} pull_failed=0"
            )

    lines = [
        "appsecgate sync: "
        f"exported={len(exported.events)} appended={appended} "
        f"sent={len(result.sent)} rejected={len(result.rejected)} "
        f"failed={len(result.failed)} {pull_summary}"
    ]
    for error in result.errors:
        lines.append(f"warning: {error}")
    if pull_error is not None:
        lines.append(f"warning: pull: {pull_error}")
    print("\n".join(lines))
    return 1 if result.failed or pull_error is not None else 0
