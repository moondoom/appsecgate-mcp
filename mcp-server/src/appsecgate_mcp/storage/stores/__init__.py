"""Store-классы предметной области — по классу на модуль (AGENTS.md, File Size Limits).

Пакет сохраняет публичный API прежнего ``storage/stores.py``: все классы
импортируются отсюда, поэтому ``from appsecgate_mcp.storage.stores import ...``
остаётся валидным.

``_now_iso`` — единственная точка времени. Тесты патчат именно
``storage.stores._now_iso`` (test_logical_id_redactor.py, test_project_identity.py),
поэтому подмодули обращаются к ней отложенно через ``_now()``, а не импортируют
значение на старте.
"""

from __future__ import annotations

from appsecgate_mcp.storage.stores._time import _now, _now_iso
from appsecgate_mcp.storage.stores.feedback import FeedbackStore
from appsecgate_mcp.storage.stores.finding_context import FindingContextStore
from appsecgate_mcp.storage.stores.finding_identity import FindingIdentityStore
from appsecgate_mcp.storage.stores.fix_attempts import FixAttemptsStore
from appsecgate_mcp.storage.stores.projects import ProjectsStore
from appsecgate_mcp.storage.stores.remote_suppression import RemoteSuppressionStore
from appsecgate_mcp.storage.stores.scan_cache import ScanCacheStore
from appsecgate_mcp.storage.stores.shown_findings import ShownFindingsStore
from appsecgate_mcp.storage.stores.sql_audit_log import SqlAuditLogStore
from appsecgate_mcp.storage.stores.suppression import SuppressionStore

__all__ = [
    "FeedbackStore",
    "FindingContextStore",
    "FindingIdentityStore",
    "FixAttemptsStore",
    "ProjectsStore",
    "RemoteSuppressionStore",
    "ScanCacheStore",
    "ShownFindingsStore",
    "SqlAuditLogStore",
    "SuppressionStore",
    "_now",
    "_now_iso",
]
