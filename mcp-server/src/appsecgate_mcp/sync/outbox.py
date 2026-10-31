"""Durable outbox очереди событий на master (MS-3, ADR-0004 §4.2).

Файл-журнал `~/.appsecgate/sync/outbox.ndjson` — одна строка = одно событие.
Записи атомарные (temp + os.replace); после успешного push отправленные
строки удаляются переписыванием файла. Битые JSON-строки карантинятся в
sidecar `*.corrupt`, события, отвергнутые master (4xx), — в `*.rejected`,
чтобы не блокировать очередь.

Идемпотентность: push повторяет строки, ещё не получившие 2xx; master
дедуплицирует по `client_event_id` (ADR-0004 §5.1).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _atomic_rewrite(path: Path, lines: list[str]) -> None:
    """Атомарная замена файла: temp в той же директории, затем os.replace."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Outbox:
    """NDJSON-очередь событий с дедупом по `client_event_id`."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, events: list[dict[str, Any]]) -> int:
        """Добавляет события, отсутствующие в очереди; возвращает число добавленных."""
        existing: set[str] = set()
        for line in self._read_raw_lines():
            try:
                eid = json.loads(line).get("client_event_id")
            except (json.JSONDecodeError, TypeError):
                continue
            if eid:
                existing.add(eid)
        fresh = [e for e in events if e.get("client_event_id") not in existing]
        if not fresh:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            *self._read_raw_lines(),
            *[json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in fresh],
        ]
        _atomic_rewrite(self.path, lines)
        return len(fresh)

    def read(self) -> list[dict[str, Any]]:
        """Читает очередь; битые строки перекладывает в `*.corrupt`."""
        valid: list[dict[str, Any]] = []
        corrupt: list[str] = []
        remaining: list[str] = []
        for line in self._read_raw_lines():
            try:
                valid.append(json.loads(line))
                remaining.append(line)
            except (json.JSONDecodeError, TypeError):
                corrupt.append(line)
        if corrupt:
            self._append_lines(corrupt, Path(f"{self.path}.corrupt"))
            if remaining:
                _atomic_rewrite(self.path, remaining)
            else:
                _atomic_rewrite(self.path, [])
        return valid

    def remove(self, sent_ids: set[str]) -> int:
        """Удаляет отправленные события; возвращает число удалённых."""
        return self._filter_out(sent_ids, keep_in_sidecar=False)

    def quarantine(self, rejected_ids: set[str]) -> int:
        """Переносит отвергнутые master события в `*.rejected`; возвращает число."""
        return self._filter_out(rejected_ids, keep_in_sidecar=True)

    def _filter_out(self, ids: set[str], *, keep_in_sidecar: bool) -> int:
        kept: list[str] = []
        moved: list[str] = []
        for line in self._read_raw_lines():
            try:
                eid = json.loads(line).get("client_event_id")
            except (json.JSONDecodeError, TypeError):
                kept.append(line)
                continue
            if eid in ids:
                moved.append(line)
            else:
                kept.append(line)
        if moved and keep_in_sidecar:
            self._append_lines(moved, Path(f"{self.path}.rejected"))
        if moved:
            _atomic_rewrite(self.path, kept)
        return len(moved)

    def _read_raw_lines(self) -> list[str]:
        if not self.path.is_file():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        return [line for line in text.splitlines(keepends=True) if line.strip()]

    @staticmethod
    def _append_lines(lines: list[str], target: Path) -> None:
        with open(target, "a", encoding="utf-8") as fh:
            fh.writelines(lines)
