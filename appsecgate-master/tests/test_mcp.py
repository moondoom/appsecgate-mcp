from __future__ import annotations

import httpx2
from api_helpers import OTHER_HEADERS, PROJ_HEADERS
from helpers import make_event, uid
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def test_mcp_requires_bearer(master_client):
    response = master_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401


async def test_mcp_schema_and_read_only_query(master_client):
    verdict_id = uid()
    await master_client.app.state.events.ingest(
        [
            make_event(
                "triage_verdicted",
                at="2026-11-01T00:00:00Z",
                verdict_id=verdict_id,
                client_event_id=verdict_id,
                run_id="run-1",
                verdict="FALSE_POSITIVE",
                verdict_source="model",
                review_status="unreviewed",
                explanation="example only",
                created_at="2026-11-01T00:00:00Z",
            )
        ]
    )
    transport = httpx2.ASGITransport(app=master_client.app)
    async with httpx2.AsyncClient(
        transport=transport, base_url="http://test", headers=PROJ_HEADERS
    ) as http:
        async with streamable_http_client("http://test/mcp", http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {
                    "describe_schema",
                    "query_findings_db",
                }
                schema = await session.call_tool("describe_schema", {})
                assert schema.structuredContent["status"] == "ok"
                result = await session.call_tool(
                    "query_findings_db",
                    {"sql": "SELECT fp, verdict FROM v_triage_verdicts"},
                )
                assert result.structuredContent["row_count"] == 1
                rejected = await session.call_tool(
                    "query_findings_db", {"sql": "DELETE FROM v_triage_verdicts"}
                )
                assert rejected.structuredContent["status"] == "error"


async def test_mcp_rejects_other_project_credentials(master_client):
    transport = httpx2.ASGITransport(app=master_client.app)
    async with httpx2.AsyncClient(
        transport=transport, base_url="http://test", headers=OTHER_HEADERS
    ) as http:
        async with streamable_http_client("http://test/mcp", http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "query_findings_db",
                    {"sql": "SELECT fp FROM v_triage_verdicts"},
                )
                assert result.structuredContent["row_count"] == 0
