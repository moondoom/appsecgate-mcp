"""Реальный loopback HTTP smoke: uvicorn + stdlib urllib (контракт MS-3)."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import uvicorn
from helpers import make_event

from appsecgate_master.api import MasterSettings, create_app


def _request(
    url: str,
    *,
    api_key: str = "proj-key",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def test_uvicorn_accepts_edge_payload_and_serves_aggregate(tmp_path):
    settings = MasterSettings(
        db_path=tmp_path / "loopback.db",
        api_keys={"proj": "proj-key"},
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="critical"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.01)

    base_url = f"http://127.0.0.1:{port}"
    try:
        event = make_event("discovered", severity="high")
        body = {"events": [event.model_dump(mode="json")]}
        first = _request(f"{base_url}/v1/events", payload=body)
        duplicate = _request(f"{base_url}/v1/events", payload=body)
        findings = _request(f"{base_url}/v1/findings?project=proj")
        audit = _request(f"{base_url}/v1/audit?project=proj")

        assert first[0] == 200
        assert first[1]["outcomes"][0]["outcome"] == "accepted"
        assert duplicate[0] == 200
        assert duplicate[1]["outcomes"][0]["outcome"] == "duplicate"
        assert findings[1]["findings"][0]["status"] == "SHOWN"
        assert len(audit[1]["audit"]) == 2

        bad = make_event("verify_wont_fix", note="AKIAIOSFODNN7EXAMPLE")
        rejected = _request(
            f"{base_url}/v1/events",
            payload={"events": [bad.model_dump(mode="json")]},
        )
        assert rejected[0] == 400
        assert rejected[1]["outcomes"][0]["outcome"] == "rejected:redaction"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
    assert not thread.is_alive()
