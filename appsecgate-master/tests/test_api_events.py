"""Master API: идемпотентный ingest, per-event outcomes и обновление агрегатов."""

from __future__ import annotations

from api_helpers import PROJ_HEADERS, event_payload, push
from fastapi.testclient import TestClient
from helpers import BASE_AT, FP, make_event, shift_at

from appsecgate_master.contracts.events import SCHEMA_VERSION


def _findings(client: TestClient, **params: str):
    response = client.get(
        "/v1/findings", params={"project": "proj", **params}, headers=PROJ_HEADERS
    )
    assert response.status_code == 200
    return response.json()["findings"]


def test_push_accepted_then_duplicate_updates_findings_and_audit(master_client: TestClient):
    event = make_event("discovered", severity="high")
    first = push(master_client, [event])
    second = push(master_client, [event])
    assert first.status_code == 200
    assert first.json()["outcomes"][0]["outcome"] == "accepted"
    assert second.status_code == 200
    assert second.json()["outcomes"][0]["outcome"] == "duplicate"

    findings = _findings(master_client)
    assert len(findings) == 1
    assert findings[0]["fp"] == FP
    assert findings[0]["status"] == "SHOWN"
    assert findings[0]["severity"] == "high"
    assert "_last_event_type" not in findings[0]

    audit = master_client.get("/v1/audit", params={"project": "proj"}, headers=PROJ_HEADERS)
    assert [row["outcome"] for row in audit.json()["audit"]] == ["duplicate", "accepted"]


def test_new_event_rebuilds_materialized_aggregate(master_client: TestClient):
    assert push(master_client, [make_event("discovered")]).status_code == 200
    negative = make_event("not_found_in_scope", at=shift_at(BASE_AT, 10), missed_scan_count=2)
    assert push(master_client, [negative]).status_code == 200
    finding = _findings(master_client)[0]
    assert finding["status"] == "POTENTIALLY_FIXED"
    assert finding["missed_scan_count"] == 2


def test_mixed_batch_returns_400_and_supports_single_fallback(master_client: TestClient):
    good = make_event("discovered")
    bad = make_event(
        "verify_wont_fix",
        fp="fp-secret",
        note="AKIAIOSFODNN7EXAMPLE — секрет",
    )
    response = push(master_client, [good, bad])
    assert response.status_code == 400
    assert [row["outcome"] for row in response.json()["outcomes"]] == [
        "accepted",
        "rejected:redaction",
    ]

    retry = push(master_client, [good])
    rejected = push(master_client, [bad])
    assert retry.status_code == 200
    assert retry.json()["outcomes"][0]["outcome"] == "duplicate"
    assert rejected.status_code == 400
    assert len(_findings(master_client)) == 1


def test_wrong_schema_version_is_per_event_rejection(master_client: TestClient):
    event = make_event("discovered", schema_version=SCHEMA_VERSION + 1)
    response = push(master_client, [event])
    assert response.status_code == 400
    assert response.json()["outcomes"][0]["outcome"] == "rejected:schema_version"
    assert _findings(master_client) == []


def test_empty_batch_is_422(master_client: TestClient):
    response = master_client.post("/v1/events", headers=PROJ_HEADERS, json={"events": []})
    assert response.status_code == 422


def test_config_policy_does_not_create_finding(master_client: TestClient):
    event = make_event("config_policy", fp=None, policy={"gates": {"ci": {"block_on": ["high"]}}})
    assert push(master_client, [event]).status_code == 200
    assert _findings(master_client) == []


def test_events_request_rejects_unknown_top_level_field(master_client: TestClient):
    response = master_client.post(
        "/v1/events",
        headers=PROJ_HEADERS,
        json={"events": [event_payload(make_event("discovered"))], "unknown": True},
    )
    assert response.status_code == 422
