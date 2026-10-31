"""Тесты показанного-источника из master (ADR-0004 MS-6).

HTTP-стаб — stdlib http.server на loopback: реальный транспорт urllib,
контракт `GET /v1/findings` проверяется end-to-end (как в sync-тестах).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from appsecgate_mcp.orchestration.shown_source import (
    MasterFindingsError,
    MasterShownSource,
    ShownRecord,
    fetch_findings,
)


class _Stub:
    """HTTP-стаб: `respond(path)` -> (status, body|raw_json_string)."""

    def __init__(self, respond: Callable[[str], tuple[int, Any]]) -> None:
        self.respond = respond
        self.requests: list[dict[str, str]] = []
        self._server: HTTPServer | None = None

    def start(self) -> str:
        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                server = self.server
                collector = server.collector  # type: ignore[attr-defined]
                collector.requests.append(
                    {"path": self.path, "auth": self.headers.get("Authorization")}
                )
                status, body = collector.respond(self.path)
                raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):  # noqa: ARG002 — тишина в тестах
                pass

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self._server.collector = self  # type: ignore[attr-defined]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._server.server_port}"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()


@pytest.fixture()
def stub():
    instances: list[_Stub] = []

    def _make(respond: Callable[[str], tuple[int, Any]]) -> _Stub:
        item = _Stub(respond)
        item.start()
        instances.append(item)
        return item

    yield _make
    for item in instances:
        item.stop()


def _ok(findings: list[dict]) -> Callable[[str], tuple[int, dict]]:
    return lambda path: (200, {"project": "p1", "findings": findings})


async def test_fetch_findings_maps_fields(stub):
    srv = stub(
        _ok(
            [
                {"fp": "a", "status": "SHOWN"},
                {
                    "fp": "b",
                    "status": "SUPPRESSED",
                    "suppression_scope": "ci",
                    "suppression_expires_at": "2027-01-01T00:00:00+00:00",
                },
                {
                    "fp": "c",
                    "verified_status": "fixed",
                    "last_seen_branch": "feature/x",
                    "suppression_scope": None,
                },
            ]
        )
    )
    records = fetch_findings(srv.start(), "p1", "key")
    assert [r.fingerprint for r in records] == ["a", "b", "c"]
    assert records[0].status == "SHOWN"
    assert records[0].gate_status == "SHOWN"
    assert records[1].suppression_scope == "ci"
    assert records[1].suppression_expires_at == "2027-01-01T00:00:00+00:00"
    assert records[2].verified_status == "fixed"
    assert records[2].last_seen_branch == "feature/x"
    assert records[2].shown_at is None  # master уже свёрнут, retention не нужен


async def test_fetch_findings_empty_and_auth(stub):
    srv = stub(_ok([]))
    records = fetch_findings(srv.start(), "p1", "secret-key")
    assert records == []
    request = srv.requests[-1]
    assert request["auth"] == "Bearer secret-key"
    assert request["path"].startswith("/v1/findings?project=p1")


async def test_fetch_findings_http_error(stub):
    srv = stub(lambda path: (401, {"detail": "unauthorized"}))
    with pytest.raises(MasterFindingsError, match="HTTP 401"):
        fetch_findings(srv.start(), "p1", "bad-key")


async def test_fetch_findings_project_mismatch(stub):
    srv = stub(lambda path: (200, {"project": "other", "findings": []}))
    with pytest.raises(MasterFindingsError, match="project mismatch"):
        fetch_findings(srv.start(), "p1", "key")


async def test_fetch_findings_invalid_json(stub):
    srv = stub(lambda path: (200, "{not json"))
    with pytest.raises(MasterFindingsError, match="invalid JSON"):
        fetch_findings(srv.start(), "p1", "key")


async def test_fetch_findings_findings_not_list(stub):
    srv = stub(lambda path: (200, {"project": "p1", "findings": {"fp": "a"}}))
    with pytest.raises(MasterFindingsError, match="findings must be a list"):
        fetch_findings(srv.start(), "p1", "key")


async def test_fetch_findings_finding_without_fp(stub):
    srv = stub(_ok([{"status": "SHOWN"}]))
    with pytest.raises(MasterFindingsError, match="'fp'"):
        fetch_findings(srv.start(), "p1", "key")


async def test_fetch_findings_network_error():
    # Порт 1 на loopback почти всегда закрыт → connection refused (URLError).
    with pytest.raises(MasterFindingsError, match="GET /v1/findings"):
        fetch_findings("http://127.0.0.1:1", "p1", "key", timeout=1)


async def test_master_source_returns_record_and_none():
    source = MasterShownSource([ShownRecord(fingerprint="fp", suppression_scope="global")])
    record = await source.record("fp")
    assert record is not None
    assert record.suppression_scope == "global"
    assert await source.record("unknown") is None
