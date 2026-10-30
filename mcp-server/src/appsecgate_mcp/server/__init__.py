"""MCP Server Layer — FastMCP-сервер AppSecGate (Фаза 1).

Модуль-фасад: публичный API (сессия, тулы, точка входа) реэкспортируется из
подмодулей, поэтому существующие импорты вида
``from appsecgate_mcp.server import mcp, SessionState, main`` остаются валидными.
Регистрация MCP-тулов происходит при импорте ``server.tools``.

Тулы:
  scan_file, scan_diff, scan_project, get_fix_context, get_fix_context_batch,
  verify_fix, verify_fix_batch, query_findings_db, export_snapshot, get_config,
  update_config, submit_feedback, get_scan_history, suppress_finding

Hook-хендлеры (session_start, pre_tool_use, post_tool_use) не являются
MCP-инструментами: они живут в hooks.py и вызываются через CLI
`appsecgate-mcp hook <name>`.

Тесты патчат атрибуты этого пакета (``server._session``, ``server._ensure_session``,
``server.init_databases``, ``server.sync_trivy_db``, ``server._configure_http``,
``server._replace_file``, ``server.ScannerRegistry``). Подмодули обращаются к
ним отложенно через ``import appsecgate_mcp.server`` в момент вызова, поэтому
подмены видны.
"""

from __future__ import annotations

from appsecgate_mcp.rules import (  # noqa: F401
    TrivyDbStatus,
    seed_trivy_db,
    sync_trivy_db,
    trivy_db_status,
)
from appsecgate_mcp.scanners.registry import ScannerRegistry
from appsecgate_mcp.server import tools as _tools  # noqa: F401  (регистрирует MCP-тулы)
from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.cli import _build_parser, _configure_http, main  # noqa: F401
from appsecgate_mcp.server.logging_utils import _log_tool, _response_size  # noqa: F401
from appsecgate_mcp.server.output import (  # noqa: F401
    _build_announce_output,
    _build_scan_output,
    _by_file_top10,
)
from appsecgate_mcp.server.session import (  # noqa: F401
    _WRITE_TOOLS,
    SessionState,
    _compute_project_id,
    _ensure_session,
    _resolve_default_project,
    _resolve_inside_project,
    _retention_cutoff,
    _session,
)
from appsecgate_mcp.server.tools.config import (  # noqa: F401
    _atomic_write,
    _replace_file,
    get_config,
    update_config,
)
from appsecgate_mcp.server.tools.context import get_fix_context, get_fix_context_batch
from appsecgate_mcp.server.tools.feedback import submit_feedback, suppress_finding
from appsecgate_mcp.server.tools.history import (  # noqa: F401
    _relative_project_path,
    get_scan_history,
)
from appsecgate_mcp.server.tools.query import export_snapshot, query_findings_db
from appsecgate_mcp.server.tools.scan import scan_diff, scan_file, scan_project
from appsecgate_mcp.server.tools.verify import verify_fix, verify_fix_batch
from appsecgate_mcp.storage.db import init_databases
from appsecgate_mcp.storage.logical_id import compute_logical_id  # noqa: F401

__all__ = [
    "SessionState",
    "TrivyDbStatus",
    "ScannerRegistry",
    "init_databases",
    "mcp",
    "main",
    "scan_file",
    "scan_diff",
    "scan_project",
    "get_config",
    "update_config",
    "submit_feedback",
    "get_scan_history",
    "suppress_finding",
    "get_fix_context",
    "get_fix_context_batch",
    "verify_fix",
    "verify_fix_batch",
    "query_findings_db",
    "export_snapshot",
]
