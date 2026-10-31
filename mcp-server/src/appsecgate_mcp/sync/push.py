"""Идемпотентный push outbox-очереди на master (MS-3, ADR-0004 §4.2/§5.2).

Транспорт — stdlib `urllib` (Q3: ноль новых зависимостей). POST
`{master}/v1/events` с телом `{"events": [...]}`; идемпотентность
обеспечивается `client_event_id` (дедуп на master, §5.1).

Семантика ответов:
- 2xx — событие доставлено;
- 4xx — постоянная ошибка (секрет в reason, неизвестное поле) → карантин;
- 5xx / сетевая ошибка — retry следующим запуском (событие остаётся в очереди).

При 4xx на батче выполняется fallback по одному событию: одно невалидное
событие не должно блокировать остальную очередь.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from appsecgate_mcp.sync.outbox import Outbox

DEFAULT_TIMEOUT = 30
DEFAULT_BATCH_SIZE = 200


class PushError(ValueError):
    """Транспортная ошибка push (сеть, таймаут, недоступный master)."""


@dataclass(slots=True)
class PushResult:
    """Итог push: доставленные / отвергнутые / оставшиеся в очереди события."""

    sent: set[str] = field(default_factory=set)
    rejected: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


def _post(url: str, events: list[dict[str, Any]], api_key: str, timeout: float) -> int:
    """POST батча событий; возвращает HTTP-статус, бросает PushError на сети."""
    body = json.dumps({"events": events}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PushError(str(exc)) from exc


def _push_single(
    event: dict[str, Any],
    endpoint: str,
    api_key: str,
    timeout: float,
    result: PushResult,
) -> None:
    """Fallback-пуша одного события после 4xx батча."""
    eid = event.get("client_event_id")
    try:
        status = _post(endpoint, [event], api_key, timeout)
    except PushError as exc:
        result.failed.add(eid)
        result.errors.append(str(exc))
        return
    if 200 <= status < 300:
        result.sent.add(eid)
    elif 400 <= status < 500:
        result.rejected.add(eid)
        result.errors.append(f"rejected {eid}: HTTP {status}")
    else:
        result.failed.add(eid)
        result.errors.append(f"server error: HTTP {status}")


def push_outbox(
    outbox: Outbox,
    master_url: str,
    api_key: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timeout: float = DEFAULT_TIMEOUT,
) -> PushResult:
    """Пушит очередь на master и чистит её по результату.

    Очередь модифицируется только по итогам ответов: отправленные удаляются,
    отвергнутые (4xx) карантинятся, остальные остаются для retry.
    """
    endpoint = f"{master_url.rstrip('/')}/v1/events"
    result = PushResult()
    events = outbox.read()
    for start in range(0, len(events), batch_size):
        batch = events[start : start + batch_size]
        try:
            status = _post(endpoint, batch, api_key, timeout)
        except PushError as exc:
            result.failed.update(e.get("client_event_id") for e in batch)
            result.errors.append(str(exc))
            continue
        if 200 <= status < 300:
            result.sent.update(e.get("client_event_id") for e in batch)
            continue
        if 400 <= status < 500:
            for event in batch:
                _push_single(event, endpoint, api_key, timeout, result)
            continue
        result.failed.update(e.get("client_event_id") for e in batch)
        result.errors.append(f"server error: HTTP {status}")

    if result.sent:
        outbox.remove(result.sent)
    if result.rejected:
        outbox.quarantine(result.rejected)
    return result
