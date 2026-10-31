"""Master API: health, Bearer-аутентификация, изоляция проектов и OpenAPI."""

from __future__ import annotations

import pytest
from api_helpers import OTHER_HEADERS, PROJ_HEADERS, push
from fastapi.testclient import TestClient
from helpers import make_event

from appsecgate_master.api import MasterSettings, create_app


def test_health_does_not_require_auth(master_client: TestClient):
    response = master_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_missing_or_unknown_key_is_401(master_client: TestClient, headers: dict[str, str]):
    response = master_client.get("/v1/findings", params={"project": "proj"}, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_key_cannot_read_another_project(master_client: TestClient):
    response = master_client.get("/v1/findings", params={"project": "other"}, headers=PROJ_HEADERS)
    assert response.status_code == 403


def test_key_cannot_push_another_project(master_client: TestClient):
    event = make_event("discovered", project_key="other")
    assert push(master_client, [event]).status_code == 403
    audit = master_client.get("/v1/audit", params={"project": "other"}, headers=OTHER_HEADERS)
    assert audit.json()["audit"] == []


def test_mixed_project_batch_is_rejected_before_ingest(master_client: TestClient):
    events = [make_event("discovered"), make_event("discovered", project_key="other")]
    assert push(master_client, events).status_code == 403
    findings = master_client.get("/v1/findings", params={"project": "proj"}, headers=PROJ_HEADERS)
    assert findings.json()["findings"] == []


def test_unknown_event_field_is_422(master_client: TestClient):
    payload = make_event("discovered").model_dump(mode="json")
    payload["unexpected"] = "must not be ignored"
    response = master_client.post("/v1/events", headers=PROJ_HEADERS, json={"events": [payload]})
    assert response.status_code == 422


def test_openapi_contains_all_ms4_routes(master_client: TestClient):
    response = master_client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert set(paths) == {
        "/healthz",
        "/v1/audit",
        "/v1/config",
        "/v1/events",
        "/v1/findings",
        "/v1/suppressions",
    }
    assert paths["/v1/events"]["post"]["responses"]["200"]


def test_settings_reject_duplicate_keys(tmp_path):
    with pytest.raises(ValueError, match="unique"):
        MasterSettings(db_path=tmp_path / "master.db", api_keys={"p1": "same", "p2": "same"})


def test_settings_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPSECGATE_MASTER_DB", str(tmp_path / "env.db"))
    monkeypatch.setenv("APPSECGATE_MASTER_API_KEYS", '{"proj": "secret"}')
    settings = MasterSettings.from_env()
    assert settings.db_path == tmp_path / "env.db"
    assert settings.api_keys == {"proj": "secret"}


def test_settings_reject_invalid_env_json(monkeypatch):
    monkeypatch.setenv("APPSECGATE_MASTER_API_KEYS", "not-json")
    with pytest.raises(ValueError, match="valid JSON"):
        create_app()
