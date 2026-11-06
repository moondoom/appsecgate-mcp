from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from typing import Any

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.dependencies import CurrentRequest
from starlette.middleware import Middleware as ASGIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from appsecgate_master.storage.postgres import set_project
from appsecgate_master.storage.query import run_query

_REQUEST = CurrentRequest()
_SCHEMA = {
    "v_triage_verdicts": [
        "project_key",
        "fp",
        "verdict_id",
        "run_id",
        "verdict",
        "confidence",
        "verdict_source",
        "actor_id",
        "revision_reason",
        "review_status",
        "scanner",
        "rule_id",
        "ruleset_hash",
        "rule_hash",
        "rule_hash_status",
        "package",
        "ecosystem",
        "cve_id",
        "explanation",
        "evidence",
        "agent_version",
        "model",
        "created_at",
        "at",
    ],
    "v_triage_knowledge": [
        "verdict_id",
        "verdict",
        "rule_id",
        "package",
        "ecosystem",
        "cve_id",
        "explanation",
        "evidence",
        "created_at",
        "at",
    ],
    "v_cve": ["cve_id", "payload", "source", "fetched_at", "content_hash"],
    "v_cve_affected": ["cve_id", "ecosystem", "package", "payload"],
}
_CALLS: dict[str, list[float]] = {}


async def _authenticate(app: FastAPI, authorization: str) -> str | None:
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:]
    settings = app.state.settings
    if settings.database_url is not None:
        return await app.state.db.authenticate_key(token)
    for project, api_key in settings.api_keys.items():
        if secrets.compare_digest(token, api_key):
            return project
    return None


class BearerMiddleware:
    def __init__(self, app: Any, *, master_app: FastAPI) -> None:
        self.app = app
        self.master_app = master_app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        project = await _authenticate(self.master_app, headers.get("authorization", ""))
        if project is None:
            response = JSONResponse({"detail": "missing or invalid bearer token"}, status_code=401)
            await response(scope, receive, send)
            return
        scope["project_key"] = project
        if self.master_app.state.settings.database_url is not None:
            set_project(project)
        await self.app(scope, receive, send)


def create_master_mcp(master_app: FastAPI) -> Any:
    server = FastMCP("AppSecGate Master")

    @server.tool()
    async def describe_schema(request: Request = _REQUEST) -> dict[str, Any]:
        return {"status": "ok", "views": _SCHEMA, "project_key": request.scope["project_key"]}

    @server.tool()
    async def query_findings_db(
        sql: str,
        params: list[Any] | None = None,
        knowledge_cutoff: str | None = None,
        request: Request = _REQUEST,
    ) -> dict[str, Any]:
        project = request.scope["project_key"]
        now = time.monotonic()
        calls = [item for item in _CALLS.get(project, []) if now - item < 60]
        if len(calls) >= 10:
            return {"status": "error", "reason": "rate_limited", "retry_after": 60}
        calls.append(now)
        _CALLS[project] = calls
        try:
            result = await asyncio.wait_for(
                run_query(master_app.state.db, sql, params, project, knowledge_cutoff),
                timeout=5,
            )
        except (ValueError, TimeoutError) as exc:
            return {"status": "error", "reason": str(exc)}
        await master_app.state.audit.record_tool(
            project_key=project,
            tool="query_findings_db",
            sql_hash=hashlib.sha256(sql.encode()).hexdigest(),
            result_count=result["row_count"],
        )
        return result

    return server.http_app(
        path="/",
        middleware=[ASGIMiddleware(BearerMiddleware, master_app=master_app)],
    )
