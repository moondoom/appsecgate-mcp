"""Хелперы контрактных тестов master API."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from appsecgate_master.contracts.events import MasterEvent

PROJ_HEADERS = {"Authorization": "Bearer proj-key"}
OTHER_HEADERS = {"Authorization": "Bearer other-key"}


def event_payload(event: MasterEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


def push(
    client: TestClient,
    events: list[MasterEvent],
    *,
    headers: dict[str, str] = PROJ_HEADERS,
):
    return client.post(
        "/v1/events",
        headers=headers,
        json={"events": [event_payload(event) for event in events]},
    )
