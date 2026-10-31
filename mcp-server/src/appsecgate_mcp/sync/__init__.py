"""Edge-синхронизация с master (MS-3, ADR-0004 §4.2/§5.1, ADR-0006 §3.5).

`appsecgate-mcp sync` — процесс на хосте, вне read-only/no-network контейнера
MCP-сервера (инвариант №2 не затрагивается: серверные модули этот пакет не
импортируют, только CLI-подкоманда `sync`, по аналогии с `ci`).

Поток: локальная `shown_findings.db` (materialized state, ADR-0006 §1.6) →
реконструкция событий жизненного цикла → durable outbox
(`~/.appsecgate/sync/outbox.ndjson`) → идемпотентный push на master
(urllib, ноль новых зависимостей).
"""

from __future__ import annotations

from appsecgate_mcp.sync.export import ExportError, ExportResult, export_events
from appsecgate_mcp.sync.outbox import Outbox
from appsecgate_mcp.sync.push import PushError, PushResult, push_outbox

__all__ = [
    "ExportError",
    "ExportResult",
    "export_events",
    "Outbox",
    "PushError",
    "PushResult",
    "push_outbox",
]
