"""Источник «показанного» для CI-режима (ADR-0004 §6, MS-6).

CI не имеет доступа к локальному `shown_findings.db` машины разработчика.
Единственный канал показанного в CI — центральный master: `appsecgate ci`
тянет состояния находок проекта с `GET /v1/findings` и поставляет их
GateEngine через интерфейс `record(fp) -> ShownRecord | None` (ADR-0003 §5.3).

Snapshot-канал (ADR-0003) удалён решением владельца (2026-10-31): в CI всегда
master, недоступность/нарушение контракта — падение (exit 2), не warning.
Сеть — только у edge/CI-процесса на хосте (инвариант №2 не затрагивается).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class MasterFindingsError(ValueError):
    """Master недоступен или ответ нарушает контракт `GET /v1/findings`."""


@dataclass
class ShownRecord:
    """Запись показанной находки (состояние агрегата master, ADR-0006 §1.3).

    ``verified_status``: null | fixed | not_fixed | wont_fix.
    ``suppression_scope``: null | local | ci | global.
    ``status``: статус жизненного цикла (ADR-0006 §1.3); при отсутствии
    выводится через ``gate_status`` из ``verified_status``/``suppression_scope``.
    ``shown_at`` не заполняется: master уже свёрнут в актуальные состояния,
    retention показанного для CI не нужен.
    """

    fingerprint: str
    shown_at: str | None = None
    verified_status: str | None = None
    suppression_scope: str | None = None
    status: str | None = None
    last_seen_branch: str | None = None
    suppression_expires_at: str | None = None

    @property
    def gate_status(self) -> str:
        """Статус для гейт-матрицы ADR-0006 §2.3 (fallback для старых записей)."""
        if self.status:
            return self.status
        if self.verified_status == "fixed":
            return "FIXED"
        if self.verified_status == "wont_fix":
            return "WONT_FIX"
        if self.suppression_scope:
            return "SUPPRESSED"
        return "SHOWN"


def fetch_findings(
    master_url: str,
    project_id: str,
    api_key: str,
    *,
    timeout: float = 30,
) -> list[ShownRecord]:
    """Тянет состояния находок проекта с master (`GET /v1/findings`, MS-6).

    Контракт: JSON-объект ``{"project": <id>, "findings": [...]}``; каждая
    запись — объект с непустым ``fp`` и опциональными ``status``/
    ``verified_status``/``suppression_scope``/``last_seen_branch``/
    ``suppression_expires_at``. Любое отклонение (сеть, HTTP, схема) —
    ``MasterFindingsError``: CI-режим fail-closed (master обязателен).
    """
    query = urllib.parse.urlencode({"project": project_id})
    request = urllib.request.Request(
        f"{master_url.rstrip('/')}/v1/findings?{query}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise MasterFindingsError(f"GET /v1/findings: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MasterFindingsError(f"GET /v1/findings: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MasterFindingsError("GET /v1/findings: invalid JSON") from exc
    if not isinstance(payload, dict):
        raise MasterFindingsError("GET /v1/findings: response must be a JSON object")
    if payload.get("project") != project_id:
        raise MasterFindingsError("GET /v1/findings: project mismatch")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise MasterFindingsError("GET /v1/findings: findings must be a list")
    return [_record_from_finding(item) for item in findings]


def _record_from_finding(item: Any) -> ShownRecord:
    if not isinstance(item, dict):
        raise MasterFindingsError("GET /v1/findings: finding must be an object")
    fp = item.get("fp")
    if not isinstance(fp, str) or not fp:
        raise MasterFindingsError("GET /v1/findings: finding must have non-empty 'fp'")
    return ShownRecord(
        fingerprint=fp,
        verified_status=item.get("verified_status"),
        suppression_scope=item.get("suppression_scope"),
        status=item.get("status"),
        last_seen_branch=item.get("last_seen_branch"),
        suppression_expires_at=item.get("suppression_expires_at"),
    )


class MasterShownSource:
    """Показанный-источник поверх состояний master (интерфейс ``record``)."""

    def __init__(self, records: list[ShownRecord]) -> None:
        self._index = {record.fingerprint: record for record in records}

    async def record(self, fingerprint: str) -> ShownRecord | None:
        return self._index.get(fingerprint)
