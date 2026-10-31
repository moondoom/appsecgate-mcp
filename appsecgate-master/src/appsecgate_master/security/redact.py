"""Redaction на приёме master-событий (инвариант №4, ADR-0004 §5.4).

Копия чистых функций из ``mcp-server .../normalization/redactor.py`` (без
зависимости от моделей mcp-server): паттерны известных секретов + high-entropy.
master — независимый деплоймент, общий модуль появится только при рефакторинге
обоих пакетов (вне скоупа MS-2).

Приём (§5.4): если ``note``/``reason`` события содержат признаки секрета —
событие отбрасывается (outcome ``rejected:redaction``) и попадает только в
``audit_log``. Ни один секрет не записывается в ``events``.
"""

from __future__ import annotations

import base64
import binascii
import math
import re

REDACTED = "[REDACTED]"

# Паттерны известных секретов (arch §4.9): AWS / GCP / Azure, PEM, JWT.
# Без backslash-эскейпов: [.] = литеральная точка, [ ] = пробел, '-' в конце
# класса не требует экранирования, DOTALL заменяет [\s\S].
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # PEM-блоки (приватные ключи, сертификаты) — маскируем весь блок целиком.
    re.compile(
        r"-----BEGIN [A-Z0-9 ]+-----.*?-----END [A-Z0-9 ]+-----",
        re.IGNORECASE | re.DOTALL,
    ),
    # Одинокая PEM-шапка, если блок обрезан сниппетом.
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?(?:PRIVATE KEY|CERTIFICATE)-----"),
    # AWS access key id (AKIA...) + 16 символов ключа.
    re.compile(r"(?:A3T[A-Z0-9]|AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[A-Z0-9]{16}"),
    # GCP OAuth client secret (YA29...) и service account key.
    re.compile(r"YA29[.][0-9A-Za-z_-]+"),
    # Azure connection string / shared key.
    re.compile(
        r"DefaultEndpointsProtocol=https?;AccountName=[^;]+;AccountKey=[A-Za-z0-9+/=]+",
        re.IGNORECASE,
    ),
    # JWT (header.payload.signature).
    re.compile(r"eyJ[A-Za-z0-9_-]+[.][A-Za-z0-9_-]+[.][A-Za-z0-9_-]{16,}"),
    # Generic API-токены / ключи: «key=», «secret=», «password=».
    re.compile(
        r"""(?i)(?:api[_-]?key|secret|token|password|passwd|pwd)"""
        r"""[ ]*[=:][ ]*["']?[A-Za-z0-9_+/=-]{10,}""",
    ),
]

# High-entropy: Shannon > 4.5 на строку длиной >= 16 (без пробелов/символов).
_ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9_+/=-]{16,}")


def _shannon_entropy(text: str) -> float:
    """Энтропия Шеннона по байтам строки (бит на символ)."""
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(text)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def _looks_base64(text: str) -> bool:
    """True, если строка похожа на base64 и корректно декодируется."""
    if len(text) % 4 != 0:
        return False
    try:
        base64.b64decode(text, validate=True)
        return True
    except (binascii.Error, ValueError):
        return False


def _mask_high_entropy(text: str) -> str:
    """Маскирует high-entropy-токены (Shannon > 4.5, len >= 16)."""

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if _shannon_entropy(token) > 4.5 or _looks_base64(token):
            return REDACTED
        return token

    return _ENTROPY_TOKEN.sub(repl, text)


def redact_text(text: str) -> str:
    """Маскирует известные паттерны и high-entropy-строки в сыром тексте."""
    if not text:
        return text
    masked = text
    for pattern in _SECRET_PATTERNS:
        masked = pattern.sub(REDACTED, masked)
    return _mask_high_entropy(masked)


def contains_suspected_secret(text: str | None) -> bool:
    """True, если текст содержит признаки секрета (для отбрасывания события).

    Сравнение с результатом redact_text: если маскирование что-то изменило —
    в тексте есть секрет (ADR-0004 §5.4).
    """
    if not text:
        return False
    return redact_text(text) != text


__all__ = ["REDACTED", "redact_text", "contains_suspected_secret"]
