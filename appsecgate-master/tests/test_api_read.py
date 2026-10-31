"""Master API: findings, suppressions, config policy и audit read-контракты."""

from __future__ import annotations

from api_helpers import OTHER_HEADERS, PROJ_HEADERS, push
from fastapi.testclient import TestClient
from helpers import BASE_AT, make_event, shift_at


def test_findings_filter_by_state_and_project(master_client: TestClient):
    shown = make_event("discovered", fp="shown")
    fixed_events = [
        make_event("discovered", fp="fixed"),
        make_event("not_found_in_scope", fp="fixed", at=shift_at(BASE_AT, 1)),
        make_event("verify_fixed", fp="fixed", at=shift_at(BASE_AT, 2)),
    ]
    other = make_event("discovered", project_key="other", fp="other-fp")
    assert push(master_client, [shown, *fixed_events]).status_code == 200
    assert push(master_client, [other], headers=OTHER_HEADERS).status_code == 200

    response = master_client.get(
        "/v1/findings",
        params={"project": "proj", "state": "FIXED"},
        headers=PROJ_HEADERS,
    )
    assert response.status_code == 200
    assert [row["fp"] for row in response.json()["findings"]] == ["fixed"]


def test_findings_reject_unknown_state(master_client: TestClient):
    response = master_client.get(
        "/v1/findings",
        params={"project": "proj", "state": "UNKNOWN"},
        headers=PROJ_HEADERS,
    )
    assert response.status_code == 422


def test_suppressions_return_only_active_ci_and_global(master_client: TestClient):
    events = []
    for fp, scope in [("ci-fp", "ci"), ("global-fp", "global"), ("local-fp", "local")]:
        events.extend(
            [
                make_event("discovered", fp=fp),
                make_event("suppressed", fp=fp, scope=scope, at=shift_at(BASE_AT, 1)),
            ]
        )
    events.extend(
        [
            make_event("discovered", fp="expired-fp"),
            make_event(
                "suppressed",
                fp="expired-fp",
                scope="ci",
                expires_at="2020-01-01T00:00:00Z",
                at=shift_at(BASE_AT, 1),
            ),
        ]
    )
    assert push(master_client, events).status_code == 200
    response = master_client.get(
        "/v1/suppressions", params={"project": "proj"}, headers=PROJ_HEADERS
    )
    assert response.status_code == 200
    suppressions = response.json()["suppressions"]
    assert {row["fp"] for row in suppressions} == {"ci-fp", "global-fp"}
    assert {row["scope"] for row in suppressions} == {"ci", "global"}


def test_config_returns_latest_policy_by_event_time(master_client: TestClient):
    old = make_event(
        "config_policy",
        fp=None,
        at=BASE_AT,
        policy={"gates": {"ci": {"block_on": ["critical"]}}},
    )
    latest = make_event(
        "config_policy",
        fp=None,
        at=shift_at(BASE_AT, 10),
        policy={"gates": {"ci": {"block_on": ["critical", "high"]}}},
    )
    assert push(master_client, [latest, old]).status_code == 200
    response = master_client.get("/v1/config", params={"project": "proj"}, headers=PROJ_HEADERS)
    assert response.status_code == 200
    assert response.json() == {
        "project": "proj",
        "policy": {"gates": {"ci": {"block_on": ["critical", "high"]}}},
        "at": latest.at,
    }


def test_config_without_policy_returns_null(master_client: TestClient):
    response = master_client.get("/v1/config", params={"project": "proj"}, headers=PROJ_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"project": "proj", "policy": None, "at": None}


def test_audit_supports_since_and_limit(master_client: TestClient):
    assert push(master_client, [make_event("discovered", fp="a")]).status_code == 200
    assert push(master_client, [make_event("discovered", fp="b")]).status_code == 200
    response = master_client.get(
        "/v1/audit",
        params={"project": "proj", "since": "2000-01-01T00:00:00Z", "limit": 1},
        headers=PROJ_HEADERS,
    )
    assert response.status_code == 200
    assert len(response.json()["audit"]) == 1
    empty = master_client.get(
        "/v1/audit",
        params={"project": "proj", "since": "2999-01-01T00:00:00Z"},
        headers=PROJ_HEADERS,
    )
    assert empty.json()["audit"] == []


def test_audit_rejects_non_utc_since_and_invalid_limit(master_client: TestClient):
    non_utc = master_client.get(
        "/v1/audit",
        params={"project": "proj", "since": "2026-10-31T12:00:00+03:00"},
        headers=PROJ_HEADERS,
    )
    invalid_limit = master_client.get(
        "/v1/audit", params={"project": "proj", "limit": 0}, headers=PROJ_HEADERS
    )
    assert non_utc.status_code == 422
    assert invalid_limit.status_code == 422
