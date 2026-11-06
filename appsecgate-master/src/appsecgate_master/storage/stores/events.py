"""MasterEventStore — приём и хранение событий (ADR-0006 §3.4, шаги 1–3).

Приём одного события:
1. Дедуп по ``client_event_id`` (UNIQUE PK) — повторный push не пишется.
2. Проверка ``schema_version`` — несовпадение → ``rejected:schema_version``.
3. Redaction (§5.4): признаки секрета в ``note``/``reason`` →
   ``rejected:redaction``, событие не попадает в ``events``.
4. Append в ``events`` (источник истины) + запись в ``audit_log``.

Каждый приём (accepted / duplicate / rejected) фиксируется в ``audit_log``.
Таблица ``events`` append-only: BEFORE UPDATE/DELETE-триггеры это enforce.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from appsecgate_master.contracts.events import SCHEMA_VERSION, MasterEvent
from appsecgate_master.security.redact import contains_suspected_secret
from appsecgate_master.storage.db import Database
from appsecgate_master.storage.stores.audit import AuditLogStore

_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS events (
    client_event_id TEXT PRIMARY KEY,  -- UUID push-события (идемпотентность)
    event_id        TEXT,              -- ID в event-log (snapshot §3.3); NULL для push
    project_key     TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    fp              TEXT,
    at              TEXT NOT NULL,     -- UTC ISO-8601
    payload         TEXT NOT NULL,     -- redacted JSON (MasterEvent)
    received_at     TEXT NOT NULL      -- UTC ISO-8601
);
CREATE INDEX IF NOT EXISTS idx_events_project_at ON events (project_key, at);
CREATE INDEX IF NOT EXISTS idx_events_project_fp ON events (project_key, fp);
CREATE TRIGGER IF NOT EXISTS trg_events_append_only_update
BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_events_append_only_delete
BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
"""


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """Результат приёма одного события."""

    client_event_id: str
    outcome: str  # accepted | duplicate | rejected:<reason>


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _has_suspected_secret(event: MasterEvent) -> bool:
    """Признаки секрета в свободных текстовых полях (§5.4)."""
    evidence = json.dumps(event.evidence, ensure_ascii=False) if event.evidence else None
    return any(
        contains_suspected_secret(value)
        for value in (event.note, event.reason, event.explanation, evidence)
    )


class MasterEventStore:
    """Append-only таблица ``events`` + приём с дедупом/валидацией/redaction."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.audit = AuditLogStore(db)

    async def init_schema(self) -> None:
        await self.db.execute_script(_EVENTS_DDL)

    async def ingest(self, events: Sequence[MasterEvent]) -> list[IngestOutcome]:
        """Принять события батчем. Outcomes соответствуют порядку events."""
        return [await self._ingest_one(event) for event in events]

    async def _ingest_one(self, event: MasterEvent) -> IngestOutcome:
        received_at = _utc_now()
        existing = await self.db.fetchone(
            "SELECT 1 FROM events WHERE client_event_id = ?", (event.client_event_id,)
        )
        if existing is not None:
            await self.audit.record(event, "duplicate", received_at)
            return IngestOutcome(event.client_event_id, "duplicate")

        if event.schema_version != SCHEMA_VERSION:
            await self.audit.record(event, "rejected:schema_version", received_at)
            return IngestOutcome(event.client_event_id, "rejected:schema_version")

        if _has_suspected_secret(event):
            await self.audit.record(event, "rejected:redaction", received_at)
            return IngestOutcome(event.client_event_id, "rejected:redaction")

        inserted = await self.db.execute_rowcount(
            "INSERT INTO events (client_event_id, event_id, project_key, event_type, fp, at,"
            " payload, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.client_event_id,
                event.event_id,
                event.project_key,
                event.event_type.value,
                event.fp,
                event.at,
                event.model_dump_json(),
                received_at,
            ),
        )
        outcome = "accepted" if inserted else "duplicate"
        await self.audit.record(event, outcome, received_at)
        return IngestOutcome(event.client_event_id, outcome)

    async def list_events(
        self,
        *,
        project_key: str | None = None,
        since: str | None = None,
        limit: int = 1000,
    ) -> list[MasterEvent]:
        """Все события с фильтрами; сортировка — порядок replay (§3.3)."""
        clauses: list[str] = []
        params: list[str] = []
        if project_key is not None:
            clauses.append("project_key = ?")
            params.append(project_key)
        if since is not None:
            clauses.append("at >= ?")
            params.append(since)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = await self.db.fetchall(
            f"SELECT client_event_id, event_id, payload FROM events{where}"
            " ORDER BY at, client_event_id LIMIT ?",
            [*params, str(limit)],
        )
        events = [_parse_event(row) for row in rows]
        events.sort(key=MasterEvent.sort_key)
        return events

    async def count(self, *, project_key: str | None = None) -> int:
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS n FROM events WHERE ? IS NULL OR project_key = ?",
            (project_key, project_key),
        )
        return int(row["n"]) if row else 0


def _parse_event(row: sqlite3.Row) -> MasterEvent:
    """Собрать MasterEvent из payload + event_id из таблицы (если есть)."""
    event = MasterEvent.model_validate_json(str(row["payload"]))
    stored_id = row["event_id"]
    if stored_id is not None and event.event_id != stored_id:
        event = event.model_copy(update={"event_id": stored_id})
    return event
