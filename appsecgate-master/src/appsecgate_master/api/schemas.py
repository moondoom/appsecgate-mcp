"""Публичные request/response-модели master API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from appsecgate_master.contracts.events import MasterEvent


class AttributesModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EventsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[MasterEvent] = Field(min_length=1)


class IngestOutcomeResponse(BaseModel):
    client_event_id: str
    outcome: str


class EventsResponse(BaseModel):
    outcomes: list[IngestOutcomeResponse]


class FindingResponse(AttributesModel):
    project_key: str
    fp: str
    status: str | None
    severity: str | None
    first_seen_at: str | None
    last_seen_at: str | None
    first_seen_branch: str | None
    first_seen_commit: str | None
    last_seen_branch: str | None
    last_seen_commit: str | None
    scan_count: int
    missed_scan_count: int
    suppression_scope: str | None
    suppression_expires_at: str | None
    suppressed_at: str | None
    suppress_reason: str | None
    affects_ci: bool
    wont_fix_at: str | None
    wont_fix_reason: str | None
    verified_status: str | None
    verified_at: str | None
    status_updated_at: str | None


class FindingsResponse(BaseModel):
    project: str
    findings: list[FindingResponse]


class SuppressionResponse(BaseModel):
    fp: str
    scope: Literal["ci", "global"]
    reason: str | None
    expires_at: str | None
    suppressed_at: str | None


class SuppressionsResponse(BaseModel):
    project: str
    suppressions: list[SuppressionResponse]


class ConfigResponse(BaseModel):
    project: str
    policy: dict[str, Any] | None
    at: str | None


class AuditEntryResponse(BaseModel):
    id: int
    client_event_id: str
    project_key: str
    fp: str | None
    event_type: str
    outcome: str
    received_at: str


class AuditResponse(BaseModel):
    project: str
    audit: list[AuditEntryResponse]


class HealthResponse(BaseModel):
    status: Literal["ok"]
