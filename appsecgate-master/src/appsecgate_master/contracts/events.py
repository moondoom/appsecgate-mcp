"""Контракт MasterEvent — единый формат push-события на master.

Источники спеки:
- ADR-0006 §1.4 — типы событий жизненного цикла (discovered … reopened).
- ADR-0004 §5.1 — поля события (project_key, client_event_id, at, …) и
  событие config_policy (справочная синхронизация политик).
- ADR-0006 §3.3 — snapshot-формат события (event_id, event, at, branch/commit).

Поля finding-событий обязательны: fp. Для suppressed обязателен scope,
для verify_* — verified_status. at/expires_at — только UTC (ISO-8601).

Секреты в note/reason отбрасываются на приёме (ADR-0004 §5.4, инвариант №4),
см. appsecgate_master.security.redact.
"""

from __future__ import annotations

import enum
import uuid as _uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = 1

# Явный UTC-дельта для валидации (tzinfo.utcoffset(dt) может вернуть None).
_UTC = timedelta(0)


class EventType(enum.StrEnum):
    """Типы событий жизненного цикла (ADR-0006 §1.4) + config_policy (§5.1)."""

    DISCOVERED = "discovered"  # positive-merge новой находки (SHOWN)
    REAFFIRMED = "reaffirmed"  # positive-merge существующей
    NOT_FOUND_IN_SCOPE = "not_found_in_scope"  # negative-merge
    VERIFY_FIXED = "verify_fixed"  # verify_fix(reported=fixed), не найдена
    VERIFY_NOT_FIXED = "verify_not_fixed"  # verify_fix(not_fixed) или fixed→найдена
    VERIFY_WONT_FIX = "verify_wont_fix"  # verify_fix(reported=wont_fix)
    SUPPRESSED = "suppressed"  # suppress_finding(scope=local|ci|global)
    SUPPRESSION_EXPIRED = "suppression_expired"  # expires_at в прошлом
    UNSUPPRESSED = "unsuppressed"  # явное снятие suppression/WONT_FIX
    REOPENED = "reopened"  # positive-merge поверх FIXED (новый цикл)
    CONFIG_POLICY = "config_policy"  # справочная синхронизация политик (§5.1)
    TRIAGE_VERDICTED = "triage_verdicted"  # версионированный LLM/human verdict

    @classmethod
    def finding_types(cls) -> set[EventType]:
        """Все типы, кроме справочного config_policy."""
        return set(cls) - {cls.CONFIG_POLICY}


class MasterEvent(BaseModel):
    """Одно push-событие. Валидируется при парсинге и перед записью в events."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    # ID в event-log (§3.3). Присутствует в snapshot-событиях; на master
    # присваивается при приёме. Tie-break при равных at: (event_id | client_event_id).
    event_id: str | None = None
    # UUID push-события edge-сервера — ключ идемпотентного приёма (ADR-0004 §5.1).
    client_event_id: str
    # Алиасы под snapshot-формат §3.3: в снапшоте поле называется event/project_id,
    # в push-контракте (§5.1) — event_type/project_key. Оба варианта парсятся.
    project_key: str = Field(validation_alias=AliasChoices("project_key", "project_id"))
    event_type: EventType = Field(validation_alias=AliasChoices("event_type", "event"))
    # UTC ISO-8601: "2026-10-31T12:00:00Z" или "...+00:00".
    at: str

    # finding-контекст (discovered, reaffirmed, not_found_in_scope,
    # verify_*, suppressed, suppression_expired, unsuppressed, reopened)
    fp: str | None = None
    rule_id: str | None = None
    file: str | None = None
    line: int | None = None
    severity: str | None = None
    branch: str | None = None
    commit: str | None = None
    first_seen_branch: str | None = None
    first_seen_commit: str | None = None
    last_seen_branch: str | None = None
    last_seen_commit: str | None = None
    missed_scan_count: int | None = None

    # verify_fixed / verify_not_fixed / verify_wont_fix
    verified_status: Literal["fixed", "not_fixed", "wont_fix"] | None = None
    note: str | None = None

    # suppressed / unsuppressed / suppression_expired
    scope: Literal["local", "ci", "global"] | None = None
    reason: str | None = None
    expires_at: str | None = None
    created_by: str | None = None

    # config_policy (ADR-0004 §5.1): gates.ci.*, gates.local.*, rules.*
    policy: dict[str, Any] | None = None

    verdict_id: str | None = None
    supersedes_verdict_id: str | None = None
    run_id: str | None = None
    verdict: Literal["TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"] | None = None
    verdict_source: Literal["model", "human"] | None = None
    review_status: Literal["unreviewed", "confirmed", "rejected"] | None = None
    explanation: str | None = None
    evidence: list[dict[str, Any]] | None = None
    agent_version: str | None = None
    model: str | None = None
    model_digest: str | None = None
    prompt_sha256: str | None = None
    tool_hashes: dict[str, str] | None = None
    package: str | None = None
    ecosystem: str | None = None
    cve_id: str | None = None
    created_at: str | None = None

    @field_validator("at", "expires_at")
    @classmethod
    def _validate_utc(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"not ISO-8601 datetime: {value!r}") from exc
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) != _UTC:
            raise ValueError(f"at/expires_at must be UTC (Z or +00:00): {value!r}")
        return value

    @field_validator("client_event_id", "event_id")
    @classmethod
    def _validate_uuid(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                _uuid.UUID(value)
            except ValueError as exc:
                raise ValueError(f"not a valid UUID: {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _check_event_specific_fields(self) -> MasterEvent:
        if self.event_type is EventType.CONFIG_POLICY:
            return self
        if not self.fp:
            raise ValueError(f"finding event {self.event_type.value} requires fp")
        if self.event_type is EventType.SUPPRESSED and self.scope is None:
            raise ValueError("suppressed requires scope (local|ci|global)")
        if self.event_type is EventType.VERIFY_WONT_FIX and not self.note:
            raise ValueError("verify_wont_fix requires note (причина WONT_FIX)")
        if self.event_type is EventType.UNSUPPRESSED and self.note is None:
            raise ValueError("unsuppressed requires note (причина снятия)")
        if self.event_type is EventType.TRIAGE_VERDICTED and not all(
            (self.verdict_id, self.run_id, self.verdict, self.verdict_source, self.review_status)
        ):
            raise ValueError("triage_verdicted requires verdict identity and classification")
        return self

    def sort_key(self) -> tuple[str, str]:
        """Порядок replay: (at, event_id), tie-break — client_event_id (ADR-0006 §3.3/§3.4).

        На master event_id присваивается при приёме (uuid4), поэтому tie-break
        для master-событий детерминирован по client_event_id.
        """
        return (self.at, self.event_id or self.client_event_id)
