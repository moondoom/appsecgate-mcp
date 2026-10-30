"""Единая точка времени для store-классов.

``_now_iso`` — каноническая функция времени. Тесты патчат именно
``storage.stores._now_iso`` (test_logical_id_redactor.py, test_project_identity.py),
поэтому ``_now()`` читает её с пакета отложенно: подмена атрибута на пакете
видна в store-классах даже после импорта.
"""

from __future__ import annotations

from datetime import UTC, datetime


def _now_iso() -> str:
    """Текущая метка времени ISO-8601 (UTC). Патчится тестами."""
    return datetime.now(UTC).isoformat()


def _now() -> str:
    """Отложенный вызов ``_now_iso`` (уважает monkeypatch ``storage.stores._now_iso``)."""
    from appsecgate_mcp.storage.stores import _now_iso

    return _now_iso()
