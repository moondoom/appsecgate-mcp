"""Фабрики событий и состояний для тестов appsecgate-master."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from appsecgate_master.aggregate.state import FindingState
from appsecgate_master.contracts.events import EventType, MasterEvent

BASE_AT = "2026-10-31T12:00:00Z"

FP = "rule-id|src/app.py|42"


def uid() -> str:
    return str(uuid.uuid4())


def shift_at(at: str, minutes: int) -> str:
    """Сдвинуть UTC ISO-8601 на N минут (для детерминированного порядка)."""
    normalized = f"{at[:-1]}+00:00" if at.endswith("Z") else at
    dt = datetime.fromisoformat(normalized) + timedelta(minutes=minutes)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def make_event(
    event_type: str | EventType,
    *,
    project_key: str = "proj",
    fp: str = FP,
    at: str = BASE_AT,
    **kwargs: Any,
) -> MasterEvent:
    """Создать валидное MasterEvent; kwargs перекрывают дефолты."""
    payload: dict[str, Any] = {
        "client_event_id": uid(),
        "project_key": project_key,
        "event_type": event_type.value if isinstance(event_type, EventType) else event_type,
        "at": at,
        "fp": fp,
    }
    payload.update(kwargs)
    return MasterEvent.model_validate(payload)


# Вспомогательные поля событий, требующих обязательные атрибуты.
_EVENT_EXTRAS: dict[str, dict[str, Any]] = {
    "suppressed": {"scope": "local"},
    "verify_wont_fix": {"note": "wont fix: согласовано с командой"},
    "unsuppressed": {"note": "снято по решению команды"},
}


def prime(status: str, *, project_key: str = "proj", fp: str = FP) -> list[MasterEvent]:
    """События, приводящие агрегат в заданный статус (матрица §2.1).

    Каждое событие получает уникальный ``at`` (инкремент по минутам) —
    порядок replay детерминирован.
    """
    sequences: dict[str, list[str]] = {
        "SHOWN": ["discovered"],
        "POTENTIALLY_FIXED": ["discovered", "not_found_in_scope"],
        "FIXED": ["discovered", "not_found_in_scope", "verify_fixed"],
        "REOPENED": ["discovered", "not_found_in_scope", "verify_fixed", "reopened"],
        "SUPPRESSED": ["discovered", "suppressed"],
        "WONT_FIX": ["discovered", "verify_wont_fix"],
    }
    return [
        make_event(
            ev_type,
            project_key=project_key,
            fp=fp,
            at=shift_at(BASE_AT, index),
            **_EVENT_EXTRAS.get(ev_type, {}),
        )
        for index, ev_type in enumerate(sequences[status])
    ]


def primed_state(
    status: str, *, project_key: str = "proj", fp: str = FP
) -> tuple[FindingState, list[MasterEvent]]:
    """Собрать состояние в статусе + использованные события (для доп. событий)."""
    from appsecgate_master.aggregate.fold import fold_events

    events = prime(status, project_key=project_key, fp=fp)
    state = fold_events(events, project_key=project_key, fp=fp)
    assert state is not None
    return state, events
