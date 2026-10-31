"""MS-5: реальный urllib pull, sync CLI и project-scoped outbox."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sync_helpers import insert_shown, insert_suppression, make_db

from appsecgate_mcp.config.loader import ConfigLoader
from appsecgate_mcp.config.master_policy import load_master_policy, master_policy_path
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores import RemoteSuppressionStore, SuppressionStore
from appsecgate_mcp.sync.cli import sync_main
from appsecgate_mcp.sync.outbox import Outbox
from appsecgate_mcp.sync.pull import PullError, pull_master
from appsecgate_mcp.sync.push import push_outbox


def _start_server(responses):
    requests = []

    class _Handler(BaseHTTPRequestHandler):
        def _respond(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            requests.append(("GET", self.path, self.headers.get("Authorization")))
            status, payload = responses[path]
            if status != 200:
                self.send_error(status)
                return
            self._respond(payload)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            requests.append(("POST", self.path, body))
            self._respond({"outcomes": []})

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, requests


def _good_responses(project="pid-1"):
    return {
        "/v1/suppressions": (
            200,
            {
                "project": project,
                "suppressions": [
                    {
                        "fp": "fp-1",
                        "scope": "ci",
                        "reason": "central",
                        "expires_at": None,
                        "suppressed_at": "2026-10-31T12:00:00Z",
                    }
                ],
            },
        ),
        "/v1/config": (
            200,
            {
                "project": project,
                "policy": {"gates": {"ci": {"wont_fix_action": "block"}}},
                "at": "2026-10-31T12:00:00Z",
            },
        ),
    }


def _remote_rows(db_path, project_id="pid-1"):
    db = Database(db_path)
    db.connect()
    store = RemoteSuppressionStore(db, project_id)
    store.init_schema()
    rows = asyncio.run(store.list_all())
    db.close()
    return rows


def test_pull_applies_both_responses_and_preserves_local(tmp_path):
    path = make_db(tmp_path)
    insert_suppression(path, "local-fp", reason="mine")
    responses = _good_responses()
    server, requests = _start_server(responses)
    try:
        result = pull_master(f"http://127.0.0.1:{server.server_port}", "pid-1", "secret", tmp_path)
    finally:
        server.shutdown()
        server.server_close()

    assert result.suppression_count == 1
    assert result.policy_present
    assert [row.fingerprint for row in _remote_rows(path)] == ["fp-1"]
    assert load_master_policy(tmp_path, "pid-1")["gates"]["ci"]["wont_fix_action"] == "block"
    assert all(request[2] == "Bearer secret" for request in requests)
    assert all("project=pid-1" in request[1] for request in requests)

    db = Database(path)
    db.connect()
    local = SuppressionStore(db, "pid-1")
    assert asyncio.run(local.get("local-fp")).reason == "mine"
    db.close()


def test_pull_empty_sets_remove_previous_remote_state(tmp_path):
    path = make_db(tmp_path)
    responses = _good_responses()
    server, _ = _start_server(responses)
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        pull_master(url, "pid-1", "key", tmp_path)
        responses["/v1/suppressions"] = (200, {"project": "pid-1", "suppressions": []})
        responses["/v1/config"] = (200, {"project": "pid-1", "policy": None, "at": None})
        result = pull_master(url, "pid-1", "key", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert _remote_rows(path) == []
    assert not master_policy_path(tmp_path, "pid-1").exists()
    assert not result.policy_present


def test_invalid_config_preserves_last_good_pull(tmp_path):
    path = make_db(tmp_path)
    responses = _good_responses()
    server, _ = _start_server(responses)
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        pull_master(url, "pid-1", "key", tmp_path)
        responses["/v1/suppressions"] = (200, {"project": "pid-1", "suppressions": []})
        responses["/v1/config"] = (
            200,
            {"project": "pid-1", "policy": {"network": {"mode": "online"}}},
        )
        with pytest.raises(PullError, match="forbidden sections"):
            pull_master(url, "pid-1", "key", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert [row.fingerprint for row in _remote_rows(path)] == ["fp-1"]
    assert load_master_policy(tmp_path, "pid-1") != {}


def test_wrong_project_does_not_apply_response(tmp_path):
    make_db(tmp_path)
    responses = _good_responses(project="other")
    server, _ = _start_server(responses)
    try:
        with pytest.raises(PullError, match="project mismatch"):
            pull_master(f"http://127.0.0.1:{server.server_port}", "pid-1", "key", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert not master_policy_path(tmp_path, "pid-1").exists()


def test_http_error_preserves_existing_remote_rows(tmp_path):
    path = make_db(tmp_path)
    responses = _good_responses()
    server, _ = _start_server(responses)
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        pull_master(url, "pid-1", "key", tmp_path)
        responses["/v1/suppressions"] = (503, {})
        with pytest.raises(PullError, match="HTTP 503"):
            pull_master(url, "pid-1", "key", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert [row.fingerprint for row in _remote_rows(path)] == ["fp-1"]


def test_push_outbox_filters_by_project(tmp_path):
    responses = {}
    server, requests = _start_server(responses)
    outbox = Outbox(tmp_path / "outbox.ndjson")
    outbox.append(
        [
            {"client_event_id": "a", "project_key": "p1", "event_type": "discovered"},
            {"client_event_id": "b", "project_key": "p2", "event_type": "discovered"},
        ]
    )
    try:
        result = push_outbox(
            outbox,
            f"http://127.0.0.1:{server.server_port}",
            "key",
            project_id="p1",
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.sent == {"a"}
    assert [event["client_event_id"] for event in outbox.read()] == ["b"]
    post_body = next(request[2] for request in requests if request[0] == "POST")
    assert [event["client_event_id"] for event in post_body["events"]] == ["a"]


def _run_cli(url, tmp_path, *extra):
    return sync_main(
        [
            "--data-dir",
            str(tmp_path),
            "--outbox",
            str(tmp_path / "outbox.ndjson"),
            "--master-url",
            url,
            "--api-key",
            "key",
            "--log-level",
            "ERROR",
            *extra,
        ]
    )


def test_cli_push_pull_and_new_config_loader(tmp_path, capsys, monkeypatch):
    path = make_db(tmp_path)
    insert_shown(path, "fp-1")
    monkeypatch.setenv("APPSECGATE_MCP_HOME", str(tmp_path))
    responses = _good_responses()
    server, _ = _start_server(responses)
    try:
        assert _run_cli(f"http://127.0.0.1:{server.server_port}", tmp_path) == 0
    finally:
        server.shutdown()
        server.server_close()
    assert "pulled_suppressions=1" in capsys.readouterr().out
    assert [row.fingerprint for row in _remote_rows(path)] == ["fp-1"]
    project = tmp_path / "project"
    project.mkdir()
    config = ConfigLoader(tmp_path / "no-default.yaml").load(project, project_id="pid-1")
    assert config.gates.ci.wont_fix_action == "block"


def test_cli_pull_failure_exit_1_keeps_previous_state(tmp_path, capsys):
    path = make_db(tmp_path)
    insert_shown(path, "fp-1")
    responses = _good_responses()
    responses["/v1/config"] = (503, {})
    server, _ = _start_server(responses)
    try:
        assert _run_cli(f"http://127.0.0.1:{server.server_port}", tmp_path) == 1
    finally:
        server.shutdown()
        server.server_close()
    assert "pull_failed=1" in capsys.readouterr().out
    assert not master_policy_path(tmp_path, "pid-1").exists()


def test_cli_multi_project_requires_project_id(tmp_path, capsys):
    path = make_db(tmp_path)
    insert_shown(path, "fp-1", project_id="p1")
    insert_shown(path, "fp-2", project_id="p2")
    assert _run_cli("http://127.0.0.1:1", tmp_path) == 2
    assert "--project-id required" in capsys.readouterr().err


def test_cli_empty_db_is_noop_with_pull_skipped(tmp_path, capsys):
    make_db(tmp_path)
    responses = _good_responses()
    server, requests = _start_server(responses)
    try:
        assert _run_cli(f"http://127.0.0.1:{server.server_port}", tmp_path) == 0
    finally:
        server.shutdown()
        server.server_close()
    assert "pull=skipped" in capsys.readouterr().out
    assert not any(request[0] == "GET" for request in requests)
