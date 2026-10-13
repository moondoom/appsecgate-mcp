"""Настройка логирования AppSecGate (диагностика, Фаза 1).

Логи пишутся только в stderr: в stdio-режиме stdout занят протоколом MCP.
Опция ``--log-file`` дополнительно добавляет ротацию (``RotatingFileHandler``,
2 МБ x 3). Уровень по умолчанию ``INFO``. Настройка выполняется один раз в
точках входа (``server.main`` и ``hooks.hook_main``), идемпотентно.

Секреты в логи не попадают: содержимое вывода сканеров редактуется на месте
записи (см. ``scanners.runner``), а промпты и сырые фрагменты кода не логируются.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_LEVEL_DEFAULT = "INFO"
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _resolve_level(level: str | None) -> int:
    """Уровень из аргумента или env ``APPSECGATE_LOG_LEVEL`` (по умолчанию INFO)."""
    text = (level or os.environ.get("APPSECGATE_LOG_LEVEL") or LOG_LEVEL_DEFAULT).upper()
    numeric = getattr(logging, text, None)
    return numeric if isinstance(numeric, int) else logging.INFO


def _resolve_log_file(log_file: str | None) -> str | None:
    """Файл лога из аргумента или env ``APPSECGATE_LOG_FILE`` (по умолчанию нет)."""
    if log_file:
        return log_file
    return os.environ.get("APPSECGATE_LOG_FILE") or None


def configure_logging(level: str | None = None, log_file: str | None = None) -> None:
    """(Пере)настраивает логгер ``appsecgate_mcp``.

    Идемпотентно: повторный вызов удаляет старые handler'ы, чтобы не дублировать
    записи (например, при вызове и ``main``, и ``hook_main`` в одном процессе).
    """
    root = logging.getLogger("appsecgate_mcp")
    root.setLevel(_resolve_level(level))
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FORMAT)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    path = _resolve_log_file(log_file)
    if path:
        file_handler = RotatingFileHandler(
            path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


__all__ = ["LOG_LEVEL_DEFAULT", "LOG_MAX_BYTES", "LOG_BACKUP_COUNT", "configure_logging"]
