"""REST-маршруты master API (ADR-0004 §5.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from appsecgate_master.aggregate.state import STATUSES, FindingState
from appsecgate_master.api.auth import authenticate, authorize_project
from appsecgate_master.api.schemas import (
    AuditResponse,
    ConfigResponse,
    EventsRequest,
    EventsResponse,
    FindingResponse,
    FindingsResponse,
    HealthResponse,
    IngestOutcomeResponse,
    SuppressionResponse,
    SuppressionsResponse,
)
from appsecgate_master.contracts.events import EventType

router = APIRouter()
Authenticated = Annotated[str, Depends(authenticate)]
Project = Annotated[str, Query(min_length=1)]


def _utc_datetime(value: str) -> datetime:
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="since must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(None):
        raise HTTPException(status_code=422, detail="since must be UTC ISO-8601")
    return parsed


def _is_expired(state: FindingState) -> bool:
    if state.suppression_expires_at is None:
        return False
    return _utc_datetime(state.suppression_expires_at) <= datetime.now(UTC)


@router.post("/v1/events", response_model=EventsResponse)
async def push_events(
    payload: EventsRequest,
    request: Request,
    authenticated: Authenticated,
) -> JSONResponse:
    if any(event.project_key != authenticated for event in payload.events):
        authorize_project(authenticated, "another-project")

    outcomes = await request.app.state.events.ingest(payload.events)
    keys = {
        (event.project_key, event.fp)
        for event, outcome in zip(payload.events, outcomes, strict=True)
        if outcome.outcome in {"accepted", "duplicate"} and event.fp is not None
    }
    if keys:
        await request.app.state.aggregates.rebuild_keys(keys)

    response = EventsResponse(
        outcomes=[
            IngestOutcomeResponse(
                client_event_id=outcome.client_event_id,
                outcome=outcome.outcome,
            )
            for outcome in outcomes
        ]
    )
    rejected = any(outcome.outcome.startswith("rejected:") for outcome in outcomes)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST if rejected else status.HTTP_200_OK,
        content=response.model_dump(mode="json"),
    )


@router.get("/v1/findings", response_model=FindingsResponse)
async def list_findings(
    request: Request,
    authenticated: Authenticated,
    project: Project = ...,
    state: str | None = Query(default=None),
) -> FindingsResponse:
    authorize_project(authenticated, project)
    if state is not None and state not in STATUSES:
        raise HTTPException(status_code=422, detail=f"unknown finding state: {state}")
    states = await request.app.state.aggregates.list_states(project, status=state)
    return FindingsResponse(
        project=project,
        findings=[FindingResponse.model_validate(item) for item in states],
    )


@router.get("/v1/suppressions", response_model=SuppressionsResponse)
async def list_suppressions(
    request: Request,
    authenticated: Authenticated,
    project: Project = ...,
) -> SuppressionsResponse:
    authorize_project(authenticated, project)
    states = await request.app.state.aggregates.list_states(project, status="SUPPRESSED")
    suppressions = [
        SuppressionResponse(
            fp=item.fp,
            scope=item.suppression_scope,
            reason=item.suppress_reason,
            expires_at=item.suppression_expires_at,
            suppressed_at=item.suppressed_at,
        )
        for item in states
        if item.suppression_scope in {"ci", "global"} and not _is_expired(item)
    ]
    return SuppressionsResponse(project=project, suppressions=suppressions)


@router.get("/v1/config", response_model=ConfigResponse)
async def get_config(
    request: Request,
    authenticated: Authenticated,
    project: Project = ...,
) -> ConfigResponse:
    authorize_project(authenticated, project)
    events = await request.app.state.events.list_events(project_key=project)
    policies = [event for event in events if event.event_type is EventType.CONFIG_POLICY]
    latest = policies[-1] if policies else None
    return ConfigResponse(
        project=project,
        policy=latest.policy if latest else None,
        at=latest.at if latest else None,
    )


@router.get("/v1/audit", response_model=AuditResponse)
async def get_audit(
    request: Request,
    authenticated: Authenticated,
    project: Project = ...,
    since: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=10000),
) -> AuditResponse:
    authorize_project(authenticated, project)
    if since is not None:
        _utc_datetime(since)
    rows = await request.app.state.audit.list(project_key=project, since=since, limit=limit)
    return AuditResponse(project=project, audit=rows)


@router.get("/healthz", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
