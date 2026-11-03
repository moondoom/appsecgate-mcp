from __future__ import annotations

import concurrent.futures
import os

import psycopg
import pytest
from api_helpers import OTHER_HEADERS, PROJ_HEADERS, push
from fastapi.testclient import TestClient
from helpers import FP, make_event

from appsecgate_master.api import MasterSettings, create_app

DSN = os.environ.get("APPSECGATE_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(not DSN, reason="APPSECGATE_TEST_POSTGRES_URL is not set")


@pytest.fixture()
def postgres_client(tmp_path):
    with psycopg.connect(DSN) as connection:
        for table in ("aggregates", "events", "audit_log", "api_keys"):
            connection.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    settings = MasterSettings(
        db_path=tmp_path / "unused.db",
        api_keys={"proj": "proj-key", "other": "other-key"},
        database_url=DSN,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_postgres_ingest_duplicate_and_project_isolation(postgres_client: TestClient):
    event = make_event("discovered", severity="high")
    assert push(postgres_client, [event]).json()["outcomes"][0]["outcome"] == "accepted"
    assert push(postgres_client, [event]).json()["outcomes"][0]["outcome"] == "duplicate"

    findings = postgres_client.get(
        "/v1/findings", params={"project": "proj"}, headers=PROJ_HEADERS
    )
    assert findings.status_code == 200
    assert [item["fp"] for item in findings.json()["findings"]] == [FP]
    forbidden = postgres_client.get(
        "/v1/findings", params={"project": "other"}, headers=PROJ_HEADERS
    )
    assert forbidden.status_code == 403
    other = postgres_client.get(
        "/v1/findings", params={"project": "other"}, headers=OTHER_HEADERS
    )
    assert other.status_code == 200
    assert other.json()["findings"] == []


def test_postgres_concurrent_idempotency(postgres_client: TestClient):
    event = make_event("discovered")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: push(postgres_client, [event]), range(16)))
    outcomes = [response.json()["outcomes"][0]["outcome"] for response in responses]
    assert outcomes.count("accepted") == 1
    assert outcomes.count("duplicate") == 15
    findings = postgres_client.get(
        "/v1/findings", params={"project": "proj"}, headers=PROJ_HEADERS
    )
    assert len(findings.json()["findings"]) == 1
