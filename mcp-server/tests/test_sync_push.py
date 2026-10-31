"""Тесты push и CLI edge-синхронизации (MS-3, sync/push.py + sync/cli.py).

HTTP-стаб — stdlib http.server на loopback (127.0.0.1), реальный транспорт
urllib: контракт POST /v1/events проверяется end-to-end.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from sync_helpers import insert_shown, make_db

from appsecgate_mcp.sync.outbox import Outbox
from appsecgate_mcp.sync.push import push_outbox


class _Collector:
    """Запоминает запросы; `status_fn(path, body)` решает код ответа."""

    def __init__(self, status_fn=None):
        self.status_fn = status_fn or (lambda path, body: 200)
        self.requests: list[tuple[str, dict]] = []
        self.lock = threading.Lock()

    def respond(self, path: str, body: dict) -> int:
        with self.lock:
            self.requests.append((path, body))
            return self.status_fn(path, body)


def _start_server(collector: _Collector) -> HTTPServer:
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            status = collector.respond(self.path, body)
            payload = json.dumps({"accepted": len(body.get("events", []))}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # заглушка: не шуметь в тестах
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _event(eid: str) -> dict:
    return {"client_event_id": eid, "event_type": "discovered", "fp": f"fp-{eid}"}


def test_push_success_removes_events(tmp_path):
    collector = _Collector()
    server = _start_server(collector)
    try:
        outbox = Outbox(tmp_path / "outbox.ndjson")
        outbox.append([_event("a"), _event("b")])
        result = push_outbox(outbox, f"http://127.0.0.1:{server.server_port}", "key")
        assert result.sent == {"a", "b"}
        assert not result.failed
        assert outbox.read() == []
        path, body = collector.requests[0]
        assert path == "/v1/events"
        assert [e["client_event_id"] for e in body["events"]] == ["a", "b"]
    finally:
        server.shutdown()
        server.server_close()


def test_push_batching(tmp_path):
    collector = _Collector()
    server = _start_server(collector)
    try:
        outbox = Outbox(tmp_path / "outbox.ndjson")
        outbox.append([_event(f"e{i}") for i in range(5)])
        result = push_outbox(outbox, f"http://127.0.0.1:{server.server_port}", "key", batch_size=2)
        assert len(result.sent) == 5
        assert len(collector.requests) == 3  # 2+2+1
        assert outbox.read() == []
    finally:
        server.shutdown()
        server.server_close()


def test_push_server_error_keeps_events(tmp_path):
    collector = _Collector(lambda path, body: 500)
    server = _start_server(collector)
    try:
        outbox = Outbox(tmp_path / "outbox.ndjson")
        outbox.append([_event("a")])
        result = push_outbox(outbox, f"http://127.0.0.1:{server.server_port}", "key")
        assert result.failed == {"a"}
        assert not result.sent
        assert [e["client_event_id"] for e in outbox.read()] == ["a"]
    finally:
        server.shutdown()
        server.server_close()


def test_push_batch_4xx_falls_back_per_event(tmp_path):
    """Батч с одним невалидным событием: 4xx на батче → per-event; оба доставляются."""

    def status_fn(path, body):
        count = len(body.get("events", []))
        return 422 if count > 1 else 200

    collector = _Collector(status_fn)
    server = _start_server(collector)
    try:
        outbox = Outbox(tmp_path / "outbox.ndjson")
        outbox.append([_event("good"), _event("bad")])
        result = push_outbox(outbox, f"http://127.0.0.1:{server.server_port}", "key", batch_size=5)
        assert result.sent == {"good", "bad"}
        assert not result.rejected
        assert outbox.read() == []
    finally:
        server.shutdown()
        server.server_close()


def test_push_per_event_4xx_quarantines(tmp_path):
    """Пер-событие 4xx → rejected (в *.rejected), 2xx → удалено из очереди."""

    def status_fn(path, body):
        count = len(body.get("events", []))
        if count > 1:
            return 422  # батч отклонён → fallback по одному
        eid = body.get("events", [{}])[0].get("client_event_id", "")
        return 422 if eid == "bad" else 200

    collector = _Collector(status_fn)
    server = _start_server(collector)
    try:
        outbox = Outbox(tmp_path / "outbox.ndjson")
        outbox.append([_event("good"), _event("bad")])
        result = push_outbox(outbox, f"http://127.0.0.1:{server.server_port}", "key", batch_size=5)
        assert result.sent == {"good"}
        assert result.rejected == {"bad"}
        assert [e["client_event_id"] for e in outbox.read()] == []
        rejected = json.loads((tmp_path / "outbox.ndjson.rejected").read_text(encoding="utf-8"))
        assert rejected["client_event_id"] == "bad"
    finally:
        server.shutdown()
        server.server_close()


def test_push_network_error_keeps_events(tmp_path):
    """Master недоступен (порт закрыт) — все события остаются в очереди."""
    outbox = Outbox(tmp_path / "outbox.ndjson")
    outbox.append([_event("a")])
    # Порт 1 на loopback гарантированно закрыт для обычного пользователя.
    result = push_outbox(outbox, "http://127.0.0.1:1", "key", timeout=2)
    assert result.failed == {"a"}
    assert [e["client_event_id"] for e in outbox.read()] == ["a"]


# ---------------------------------------------------------------------------
# CLI: sync_main
# ---------------------------------------------------------------------------

from appsecgate_mcp.sync.cli import sync_main  # noqa: E402


def _run_cli(server_url: str | None, tmp_path, *extra: str) -> int:
    argv = [
        "--data-dir",
        str(tmp_path),
        "--outbox",
        str(tmp_path / "outbox.ndjson"),
        "--log-level",
        "ERROR",
    ]
    if server_url:
        argv += ["--master-url", server_url, "--api-key", "k"]
    argv += list(extra)
    return sync_main(argv)


def test_cli_dry_run_text(tmp_path, capsys):
    db = make_db(tmp_path)
    insert_shown(db, "fp-1")
    assert _run_cli(None, tmp_path, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "events=1" in out
    assert not (tmp_path / "outbox.ndjson").exists()


def test_cli_dry_run_ndjson(tmp_path, capsys):
    db = make_db(tmp_path)
    insert_shown(db, "fp-1")
    assert _run_cli(None, tmp_path, "--dry-run", "--format", "ndjson") == 0
    line = capsys.readouterr().out.strip().splitlines()[0]
    assert json.loads(line)["event_type"] == "discovered"


def test_cli_missing_db_exit_2(tmp_path, capsys):
    assert _run_cli(None, tmp_path) == 2
    assert "shown_findings.db not found" in capsys.readouterr().err


def test_cli_requires_master_url(tmp_path, capsys):
    db = make_db(tmp_path)
    insert_shown(db, "fp-1")
    assert _run_cli(None, tmp_path) == 2
    assert "--master-url required" in capsys.readouterr().err


def test_cli_full_sync_exit_0(tmp_path, capsys):
    db = make_db(tmp_path)
    insert_shown(db, "fp-1")
    collector = _Collector()
    server = _start_server(collector)
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        assert _run_cli(url, tmp_path) == 0
        out = capsys.readouterr().out
        assert "sent=1" in out
        assert "failed=0" in out
        path = tmp_path / "outbox.ndjson"
        assert not path.exists() or path.read_text(encoding="utf-8").strip() == ""
    finally:
        server.shutdown()
        server.server_close()


def test_cli_push_failure_exit_1(tmp_path, capsys):
    db = make_db(tmp_path)
    insert_shown(db, "fp-1")
    collector = _Collector(lambda path, body: 503)
    server = _start_server(collector)
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        assert _run_cli(url, tmp_path) == 1
        out = capsys.readouterr().out
        assert "failed=1" in out
        # Событие осталось в outbox для retry.
        outbox = Outbox(tmp_path / "outbox.ndjson")
        assert [e["client_event_id"] for e in outbox.read()] != []
    finally:
        server.shutdown()
        server.server_close()
