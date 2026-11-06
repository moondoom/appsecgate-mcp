"""FastAPI application factory для master-сервера."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from appsecgate_master.api.config import MasterSettings
from appsecgate_master.api.routes import router
from appsecgate_master.mcp import create_master_mcp
from appsecgate_master.storage import AggregateStore, AuditLogStore, MasterEventStore, init_schema
from appsecgate_master.storage.db import init_database


def create_app(settings: MasterSettings | None = None) -> FastAPI:
    """Создать приложение; без аргумента настройки читаются из окружения."""
    resolved = settings or MasterSettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = await init_database(resolved.db_path, resolved.database_url)
        await init_schema(db)
        if resolved.database_url is not None:
            await db.init_security(resolved.api_keys)
        app.state.db = db
        app.state.events = MasterEventStore(db)
        app.state.aggregates = AggregateStore(db)
        app.state.audit = AuditLogStore(db)
        try:
            yield
        finally:
            db.close()

    app = FastAPI(
        title="AppSecGate Master API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.include_router(router)
    mcp_app = create_master_mcp(app)

    @asynccontextmanager
    async def combined_lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with lifespan(app), mcp_app.lifespan(app):
            yield

    app.router.lifespan_context = combined_lifespan
    app.mount("/mcp", mcp_app)
    return app
