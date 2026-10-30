"""Источники «показанного» для CI-режима (ADR-0003).

Локально показанные находки живут в `shown_findings.db` на машине
разработчика; у CI к ним доступа нет. Доставка — опциональный snapshot
`.appsecgate-mcp/shown.ndjson` (пишет агент, инвариант №1 — сервер не
пишет файлы проекта). Этот модуль парсит snapshot и предоставляет
GateEngine источник с интерфейсом `record(fp) -> ShownRecord | None`
(ADR-0003 §5.3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Retention показанного совпадает с shown_findings (arch §4.7).
RETENTION_DAYS = 30


class ShownSnapshotError(ValueError):
    """Snapshot существует, но не является корректным shown.ndjson."""


@dataclass
class ShownRecord:
    """Запись показанной находки из snapshot (ADR-0003 §6.1).

    ``verified_status``: null | fixed | not_fixed | wont_fix.
    ``suppression_scope``: null | local | ci | global.
    """

    fingerprint: str
    shown_at: str | None = None
    verified_status: str | None = None
    suppression_scope: str | None = None


@dataclass
class ShownSnapshot:
    """Разобранный snapshot + служебные счётчики для warning."""

    records: list[ShownRecord] = field(default_factory=list)
    expired_count: int = 0

    def to_index(self) -> dict[str, ShownRecord]:
        return {record.fingerprint: record for record in self.records}


def _retention_cutoff(days: int, *, now: datetime | None = None) -> str:
    base = now or datetime.now(UTC)
    return (base - timedelta(days=days)).isoformat()


def parse_shown_snapshot(
    path: str | Path,
    *,
    max_age_days: int = RETENTION_DAYS,
) -> ShownSnapshot:
    """Парсит shown.ndjson в ShownSnapshot.

    Пустые строки пропускаются; некорректный JSON или запись без ``fp`` →
    ``ShownSnapshotError`` (жёсткая ошибка, а не молчаливый пропуск — иначе
    ленивый/битый snapshot тихо спрятал бы находки от CI). Просроченные по
    retention записи отбрасываются и считаются в ``expired_count``.
    """
    file_path = Path(path)
    cutoff = _retention_cutoff(max_age_days)
    records: list[ShownRecord] = []
    expired = 0
    for lineno, raw in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ShownSnapshotError(f"line {lineno}: invalid JSON: {exc}") from exc
        if not isinstance(obj, dict) or not obj.get("fp"):
            raise ShownSnapshotError(f"line {lineno}: record must be an object with 'fp'")
        record = ShownRecord(
            fingerprint=str(obj["fp"]),
            shown_at=obj.get("shown_at"),
            verified_status=obj.get("verified_status"),
            suppression_scope=obj.get("suppression_scope"),
        )
        if record.shown_at and record.shown_at < cutoff:
            expired += 1
            continue
        records.append(record)
    return ShownSnapshot(records=records, expired_count=expired)


class SnapshotShownSource:
    """Показанный-источник поверх snapshot (CI; интерфейс ``record``).

    В отличие от локального ``ShownFindingsStore.was_shown``, возвращает
    детали (``verified_status``/``suppression_scope``), по которым GateEngine
    решает по таблице ADR-0003 §5.2 (fixed / ci / global снимают блок).
    """

    def __init__(self, snapshot: ShownSnapshot) -> None:
        self._index = snapshot.to_index()

    async def record(self, fingerprint: str) -> ShownRecord | None:
        return self._index.get(fingerprint)
