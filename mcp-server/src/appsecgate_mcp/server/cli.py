"""CLI: точка входа ``appsecgate-mcp`` / ``python -m appsecgate_mcp``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import warnings
from pathlib import Path

from appsecgate_mcp.logging_setup import configure_logging
from appsecgate_mcp.server.app import mcp

logger = logging.getLogger(__name__)


def _configure_http(host: str, port: int) -> None:
    """Задаёт host/port для HTTP-транспортов (best-effort по версиям MCP)."""
    try:
        mcp.settings.host = host
        mcp.settings.port = port
    except Exception:
        os.environ.setdefault("FASTMCP_HOST", host)
        os.environ.setdefault("FASTMCP_PORT", str(port))


def _build_parser() -> argparse.ArgumentParser:
    """Собирает CLI-парсер (вынесено отдельно для тестируемости)."""
    parser = argparse.ArgumentParser(prog="appsecgate-mcp", description="AppSecGate MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default=os.environ.get("APPSECGATE_TRANSPORT", "stdio"),
        help=(
            "stdio — основной (по умолчанию); streamable-http — HTTP-демон; "
            "sse — устаревший HTTP-транспорт (deprecated, используйте streamable-http)."
        ),
    )
    parser.add_argument("--host", default=os.environ.get("APPSECGATE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("APPSECGATE_PORT", "8765")))
    parser.add_argument(
        "--project",
        default=os.environ.get("APPSECGATE_PROJECT_PATH") or os.environ.get("APPSECGATE_WORKSPACE"),
        help="Корень проекта для сканирования",
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("APPSECGATE_PROJECT_ID"),
        help=(
            "Явный project_id (T9). Перекрывает git/путь. Стабилен между сессиями "
            "независимо от пути монтирования."
        ),
    )
    parser.add_argument(
        "--project-alias",
        default=os.environ.get("APPSECGATE_PROJECT_ALIAS"),
        help=(
            "Явное имя проекта (T9): project_id = sha256('alias:' + имя)[:16]. "
            "Без него имя берётся из git-репозитория или имени каталога."
        ),
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("APPSECGATE_LOG_LEVEL", "INFO"),
        help="Уровень логирования (DEBUG/INFO/WARNING/ERROR). По умолчанию INFO.",
    )
    parser.add_argument(
        "--log-file",
        default=os.environ.get("APPSECGATE_LOG_FILE"),
        help="Файл лога с ротацией (2 МБ x 3). Без него логи пишутся только в stderr.",
    )
    return parser


def serve_main(argv: list[str] | None = None) -> None:
    """Запускает MCP-сервер с прежними аргументами командной строки."""
    args = _build_parser().parse_args(argv)
    configure_logging(args.log_level, args.log_file)
    logger.info("start appsecgate-mcp transport=%s", getattr(args, "transport", "stdio"))

    # Отложенный доступ к пакету: тесты патчат server._session / server._configure_http.
    import appsecgate_mcp.server as server_mod

    if args.project:
        server_mod._session.project_path = str(Path(args.project).resolve())
    if args.project_id:
        server_mod._session.project_id_override = args.project_id
    if args.project_alias:
        server_mod._session.project_alias_override = args.project_alias

    transport = args.transport
    if transport == "sse":
        warnings.warn(
            "Транспорт 'sse' устарел и заменён на 'streamable-http' "
            "(MCP spec 2025-03-26). Используйте --transport streamable-http.",
            DeprecationWarning,
            stacklevel=2,
        )
    if transport != "stdio":
        server_mod._configure_http(args.host, args.port)

    mcp.run(transport=transport)


def main() -> None:
    """Совместимый legacy-entrypoint с прежней диспетчеризацией подкоманд."""
    if len(sys.argv) > 1 and sys.argv[1] in {"hook", "ci", "sync", "serve", "agent"}:
        from appsecgate_mcp.cli import main as dispatch_main

        dispatch_main()
    else:
        serve_main()


if __name__ == "__main__":
    main()
