"""Экспорт локального состояния в события master (MS-3, ADR-0004 §5.1/§4.2).

Локальные SQLite-базы хранят materialized state (ADR-0006 §1.6): журнал
shown_findings + suppressions; event-log с полной историей локально не
ведётся. Экспорт РЕКОНСТРУИРУЕТ события из текущего состояния так, что
fold на master (ADR-0006 §3.4, матрица §2.1) воспроизводит тот же статус
находки.

client_event_id — детерминированный (uuid5): повторный экспорт того же
состояния даёт те же id → идемпотентный приём на master (дедуп по
client_event_id, ADR-0004 §5.1). Одинаковые логические события на разных
машинах схлопываются в один id.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
_ONE_MICROSECOND = timedelta(microseconds=1)
_NAMESPACE = uuid.NAMESPACE_DNS

# Fallback-note для verify_wont_fix, если локально причина не заполнена
# (контракт MasterEvent требует непустой note, ADR-0004 §5.1).
_WONT_FIX_DEFAULT_NOTE = "wont_fix"


@dataclass(slots=True)
class ExportResult:
    """Итог экспорта: реконструированные события + сводка."""

    events: list[dict[str, Any]]
    project_count: int
    finding_count: int
    by_event: dict[str, int] = field(default_factory=dict)


class ExportError(ValueError):
    """Локальная БД отсутствует или не соответствует ожидаемой схеме."""


def _parse_utc(value: str) -> datetime:
    """Парсит ISO-8601 UTC (Z или +00:00) — данные локальной БД хранят +00:00."""
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _minus_micros(iso: str) -> str:
    """ISO-таймстамп на 1 мкс раньше (детерминированный порядок событий).

    Для FIXED: not_found_in_scope должен сложиться до verify_fixed — при
    равных `at` порядок решает случайный tie-break по client_event_id
    (правило 5 §3.4), поэтому отсутствие фиксируется строго раньше.
    """
    return (_parse_utc(iso) - _ONE_MICROSECOND).isoformat()


def _ensure_after(value: str, minimum: str) -> str:
    """Возвращает `value`, если оно строго больше `minimum`, иначе minimum+1 мкс.

    Для REOPENED поверх FIXED: reopened должен сложиться после verify_fixed.
    """
    if value > minimum:
        return value
    return (_parse_utc(minimum) + _ONE_MICROSECOND).isoformat()


def _client_event_id(project_key: str, fp: str, event_type: str, at: str) -> str:
    """Детерминированный UUID события (uuid5): стабилен между запусками/машинами."""
    name = f"appsecgate:{project_key}:{fp}:{event_type}:{at}"
    return str(uuid.uuid5(_NAMESPACE, name))


def _base_event(row: dict[str, Any], event_type: str, at: str) -> dict[str, Any]:
    """Общие поля finding-события (push-контракт §5.1, алиасы парсятся на master)."""
    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "client_event_id": _client_event_id(row["project_id"], row["fingerprint"], event_type, at),
        "project_key": row["project_id"],
        "event_type": event_type,
        "at": at,
        "fp": row["fingerprint"],
        "rule_id": row["rule_id"],
        "file": row["file_path"],
        "severity": row["severity"],
    }
    if row.get("last_seen_branch"):
        event["last_seen_branch"] = row["last_seen_branch"]
        event["last_seen_commit"] = row.get("last_seen_commit")
    return event


def _discovered_event(row: dict[str, Any]) -> dict[str, Any]:
    """discovered: первое наблюдение (SHOWN). first_seen_branch — ветка первого показа."""
    event = _base_event(row, "discovered", row["first_seen_at"])
    event["branch"] = row.get("first_seen_branch") or row.get("last_seen_branch")
    event["commit"] = row.get("first_seen_commit") or row.get("last_seen_commit")
    if row.get("first_seen_branch"):
        event["first_seen_branch"] = row["first_seen_branch"]
        event["first_seen_commit"] = row.get("first_seen_commit")
    return event


def _reaffirmed_event(row: dict[str, Any]) -> dict[str, Any]:
    """reaffirmed: повторное наблюдение (positive-merge существующей)."""
    return _base_event(row, "reaffirmed", row["last_seen_at"])


def _status_events(row: dict[str, Any], suppression: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Реконструкция статуса в терминальные события (матрица ADR-0006 §2.1).

    SHOWN/POTENTIALLY_FIXED/FIXED/REOPENED/SUPPRESSED/WONT_FIX. Для FIXED и
    REOPENED путь в матрице требует промежуточного not_found_in_scope —
    локальная версия (verify_fix напрямую из SHOWN) в матрице отсутствует.
    """
    status = row["status"]
    if status == "POTENTIALLY_FIXED":
        return [
            {
                **_base_event(row, "not_found_in_scope", row["status_updated_at"]),
                "missed_scan_count": row.get("missed_scan_count") or 0,
            }
        ]
    if status == "FIXED":
        fixed_at = row.get("fixed_at") or row["status_updated_at"]
        return [
            {
                **_base_event(row, "not_found_in_scope", _minus_micros(fixed_at)),
                "missed_scan_count": row.get("missed_scan_count") or 0,
            },
            {
                **_base_event(row, "verify_fixed", fixed_at),
                "verified_status": "fixed",
                "note": row.get("fixed_confirmed_by") or "verify_fix",
            },
        ]
    if status == "REOPENED":
        fixed_at = row.get("fixed_at")
        if fixed_at:
            reopened_at = _ensure_after(row["status_updated_at"], fixed_at)
            return [
                {
                    **_base_event(row, "not_found_in_scope", _minus_micros(fixed_at)),
                    "missed_scan_count": row.get("missed_scan_count") or 0,
                },
                {**_base_event(row, "verify_fixed", fixed_at), "verified_status": "fixed"},
                {**_base_event(row, "reopened", reopened_at)},
            ]
        # SHOWN → REOPENED не имеет пути в матрице §2.1; аппроксимация:
        # verify_not_fixed (lands SHOWN). Оба статуса блокируют CI (§2.3).
        return [
            {
                **_base_event(row, "verify_not_fixed", row["status_updated_at"]),
                "verified_status": "not_fixed",
            }
        ]
    if status == "SUPPRESSED":
        scope = (suppression or {}).get("scope") or "local"
        event = {
            **_base_event(row, "suppressed", row.get("suppressed_at") or row["status_updated_at"]),
            "scope": scope,
            "reason": row.get("suppress_reason") or "",
        }
        expires_at = (suppression or {}).get("expires_at")
        if expires_at:
            event["expires_at"] = expires_at
        return [event]
    if status == "WONT_FIX":
        return [
            {
                **_base_event(
                    row, "verify_wont_fix", row.get("wont_fix_at") or row["status_updated_at"]
                ),
                "verified_status": "wont_fix",
                "note": row.get("wont_fix_reason") or _WONT_FIX_DEFAULT_NOTE,
            }
        ]
    return []


def _build_events(
    rows: list[Any],
    suppressions: list[Any],
    project_id: str | None,
) -> ExportResult:
    """Собирает события из строк БД (детерминированный порядок: project, fp, at)."""
    events: list[dict[str, Any]] = []
    projects: set[str] = set()
    fingerprints: set[str] = set()
    suppressed_pairs: set[tuple[str, str]] = set()
    by_event: dict[str, int] = {}

    supp_index: dict[tuple[str, str], dict[str, Any]] = {}
    for suppression in suppressions:
        supp_index[(suppression["project_id"], suppression["fingerprint"])] = dict(suppression)

    for raw in rows:
        row = dict(raw)
        if project_id is not None and row["project_id"] != project_id:
            continue
        projects.add(row["project_id"])
        fingerprints.add(row["fingerprint"])

        row_events = [_discovered_event(row)]
        last_seen = row.get("last_seen_at")
        first_seen = row.get("first_seen_at")
        if last_seen and first_seen and last_seen > first_seen:
            row_events.append(_reaffirmed_event(row))
        row_events.extend(
            _status_events(row, supp_index.get((row["project_id"], row["fingerprint"])))
        )
        for event in row_events:
            events.append(event)
            by_event[event["event_type"]] = by_event.get(event["event_type"], 0) + 1
        if row["status"] == "SUPPRESSED":
            suppressed_pairs.add((row["project_id"], row["fingerprint"]))

    # Suppressions без показанной записи (подавление до первого показа):
    # suppressed с scope/expires_at из таблицы suppressions.
    for (pid, fp), suppression in supp_index.items():
        if project_id is not None and pid != project_id:
            continue
        if (pid, fp) in suppressed_pairs:
            continue
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "client_event_id": _client_event_id(pid, fp, "suppressed", suppression["created_at"]),
            "project_key": pid,
            "event_type": "suppressed",
            "at": suppression["created_at"],
            "fp": fp,
            "scope": suppression.get("scope") or "local",
            "reason": suppression.get("reason") or "",
        }
        if suppression.get("expires_at"):
            event["expires_at"] = suppression["expires_at"]
        events.append(event)
        by_event["suppressed"] = by_event.get("suppressed", 0) + 1
        projects.add(pid)
        fingerprints.add(fp)

    events.sort(key=lambda e: (e["project_key"], e["fp"], e["at"], e["event_type"]))
    return ExportResult(
        events=events,
        project_count=len(projects),
        finding_count=len(fingerprints),
        by_event=by_event,
    )


def export_events(db_path: str | Path, project_id: str | None = None) -> ExportResult:
    """Читает локальную `shown_findings.db` и реконструирует события.

    `project_id=None` — все проекты локальной БД. Только SELECT: схема не
    трогается (инвариант №4/№5 не затрагиваются — БД читается на хосте).
    """
    path = Path(db_path)
    if not path.is_file():
        raise ExportError(f"shown_findings.db not found: {path}")

    try:
        conn = sqlite3.connect(str(path), timeout=10)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise ExportError(f"cannot open {path}: {exc}") from exc

    try:
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "shown_findings" not in tables:
            # Свежая БД без находок — экспортировать нечего (не ошибка).
            return ExportResult(events=[], project_count=0, finding_count=0)
        rows = conn.execute("SELECT * FROM shown_findings").fetchall()
        suppressions: list[Any] = []
        if "suppressions" in tables:
            suppressions = conn.execute("SELECT * FROM suppressions").fetchall()
    except sqlite3.OperationalError as exc:
        raise ExportError(f"unexpected schema in {path}: {exc}") from exc
    finally:
        conn.close()

    return _build_events(rows, suppressions, project_id)
