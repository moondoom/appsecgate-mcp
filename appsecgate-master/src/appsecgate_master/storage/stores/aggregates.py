"""AggregateStore — материализованные агрегаты (project_key, fp).

Агрегат — это кэш, пересчитываемый из append-only ``events`` через
``fold_events`` (ADR-0006 §3.3 шаг 4/§3.4). ``rebuild()`` проходит по всем
(project_key, fp) из events и upsert-ит текущее состояние. Не append-only:
строки обновляются при пересчёте — это осознанное отличие от events/audit_log.
"""

from __future__ import annotations

import sqlite3

from appsecgate_master.aggregate.fold import fold_events
from appsecgate_master.aggregate.state import FindingState
from appsecgate_master.contracts.events import MasterEvent
from appsecgate_master.storage.db import Database

_AGGREGATES_DDL = """
CREATE TABLE IF NOT EXISTS aggregates (
    project_key            TEXT NOT NULL,
    fp                     TEXT NOT NULL,
    status                 TEXT,
    severity               TEXT,
    first_seen_at          TEXT,
    last_seen_at           TEXT,
    first_seen_branch      TEXT,
    first_seen_commit      TEXT,
    last_seen_branch       TEXT,
    last_seen_commit       TEXT,
    scan_count             INTEGER NOT NULL DEFAULT 0,
    missed_scan_count      INTEGER NOT NULL DEFAULT 0,
    suppression_scope      TEXT,
    suppression_expires_at TEXT,
    suppressed_at          TEXT,
    suppress_reason        TEXT,
    affects_ci             INTEGER NOT NULL DEFAULT 1,
    wont_fix_at            TEXT,
    wont_fix_reason        TEXT,
    verified_status        TEXT,
    verified_at            TEXT,
    status_updated_at      TEXT,
    PRIMARY KEY (project_key, fp)
);
"""

_UPSERT_SQL = """
INSERT OR REPLACE INTO aggregates (
    project_key, fp, status, severity,
    first_seen_at, last_seen_at, first_seen_branch, first_seen_commit,
    last_seen_branch, last_seen_commit, scan_count, missed_scan_count,
    suppression_scope, suppression_expires_at, suppressed_at, suppress_reason,
    affects_ci, wont_fix_at, wont_fix_reason, verified_status, verified_at,
    status_updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _state_to_params(state: FindingState) -> tuple[object, ...]:
    return (
        state.project_key,
        state.fp,
        state.status,
        state.severity,
        state.first_seen_at,
        state.last_seen_at,
        state.first_seen_branch,
        state.first_seen_commit,
        state.last_seen_branch,
        state.last_seen_commit,
        state.scan_count,
        state.missed_scan_count,
        state.suppression_scope,
        state.suppression_expires_at,
        state.suppressed_at,
        state.suppress_reason,
        int(state.affects_ci),
        state.wont_fix_at,
        state.wont_fix_reason,
        state.verified_status,
        state.verified_at,
        state.status_updated_at,
    )


class AggregateStore:
    """Материализованные агрегаты; источник истины — таблица ``events``."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def init_schema(self) -> None:
        await self.db.execute_script(_AGGREGATES_DDL)

    async def rebuild(self) -> int:
        """Пересчитать все агрегаты из events. Возвращает число находок."""
        keys = await self.db.fetchall(
            "SELECT DISTINCT project_key, fp FROM events WHERE fp IS NOT NULL"
        )
        for row in keys:
            project_key = str(row["project_key"])
            fp = str(row["fp"])
            events = await self._events_for(project_key, fp)
            state = fold_events(events, project_key=project_key, fp=fp)
            if state is not None:
                await self.db.execute(_UPSERT_SQL, _state_to_params(state))
        return len(keys)

    async def get_state(self, project_key: str, fp: str) -> FindingState | None:
        row = await self.db.fetchone(
            "SELECT * FROM aggregates WHERE project_key = ? AND fp = ?", (project_key, fp)
        )
        return _row_to_state(row) if row is not None else None

    async def list_states(self, project_key: str) -> list[FindingState]:
        rows = await self.db.fetchall(
            "SELECT * FROM aggregates WHERE project_key = ? ORDER BY fp", (project_key,)
        )
        return [_row_to_state(row) for row in rows]

    async def _events_for(self, project_key: str, fp: str) -> list[MasterEvent]:
        rows = await self.db.fetchall(
            "SELECT client_event_id, event_id, payload FROM events"
            " WHERE project_key = ? AND fp = ?",
            (project_key, fp),
        )
        return [_parse_event(row) for row in rows]


def _parse_event(row: sqlite3.Row) -> MasterEvent:
    """Собрать MasterEvent из payload + event_id из таблицы (если есть)."""
    event = MasterEvent.model_validate_json(str(row["payload"]))
    stored_id = row["event_id"]
    if stored_id is not None and event.event_id != stored_id:
        event = event.model_copy(update={"event_id": stored_id})
    return event


def _row_to_state(row: sqlite3.Row) -> FindingState:
    """Собрать FindingState из строки таблицы aggregates."""
    return FindingState(
        project_key=str(row["project_key"]),
        fp=str(row["fp"]),
        status=row["status"],
        severity=row["severity"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        first_seen_branch=row["first_seen_branch"],
        first_seen_commit=row["first_seen_commit"],
        last_seen_branch=row["last_seen_branch"],
        last_seen_commit=row["last_seen_commit"],
        scan_count=int(row["scan_count"]),
        missed_scan_count=int(row["missed_scan_count"]),
        suppression_scope=row["suppression_scope"],
        suppression_expires_at=row["suppression_expires_at"],
        suppressed_at=row["suppressed_at"],
        suppress_reason=row["suppress_reason"],
        affects_ci=bool(row["affects_ci"]),
        wont_fix_at=row["wont_fix_at"],
        wont_fix_reason=row["wont_fix_reason"],
        verified_status=row["verified_status"],
        verified_at=row["verified_at"],
        status_updated_at=row["status_updated_at"],
    )
