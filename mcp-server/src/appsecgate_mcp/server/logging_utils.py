"""Обёртки логирования MCP-тулов (имя, длительность, размер ответа)."""

from __future__ import annotations

import functools
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _response_size(result: Any) -> str:
    """Компактная оценка размера ответа для лога (без полной сериализации)."""
    if isinstance(result, dict):
        if "findings" in result:
            return f"findings={len(result['findings'])}"
        if "summary" in result and isinstance(result["summary"], dict):
            return f"total={result['summary'].get('total')}"
    if isinstance(result, (dict, list)):
        return f"items={len(result)}"
    return "n/a"


def _log_tool(func: Any) -> Any:
    """Обёртка логирования MCP-тула: имя, длительность, размер ответа.

    ``functools.wraps`` сохраняет ``__name__``/``__doc__``/``__wrapped__``,
    поэтому FastMCP видит исходную сигнатуру и описание тула.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
        except Exception:
            logger.exception(
                "tool %s failed after %.2f ms",
                func.__name__,
                (time.perf_counter() - started) * 1000,
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "tool=%s duration_ms=%s response=%s",
            func.__name__,
            duration_ms,
            _response_size(result),
        )
        return result

    return wrapper
