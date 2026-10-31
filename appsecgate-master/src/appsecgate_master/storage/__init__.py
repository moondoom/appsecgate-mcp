"""Хранилище master-БД: SQLite, миграции, stores (по классу на модуль)."""

from __future__ import annotations

from appsecgate_master.storage.db import Database
from appsecgate_master.storage.stores.aggregates import AggregateStore
from appsecgate_master.storage.stores.audit import AuditLogStore
from appsecgate_master.storage.stores.events import MasterEventStore

__all__ = ["AggregateStore", "AuditLogStore", "Database", "MasterEventStore"]


async def init_schema(db: Database) -> None:
    """Создаёт все таблицы/индексы/триггеры master-БД (schema_version 1).

    Порядок: audit_log (на неё ссылается events-приём), events, aggregates.
    """
    await AuditLogStore(db).init_schema()
    await MasterEventStore(db).init_schema()
    await AggregateStore(db).init_schema()
