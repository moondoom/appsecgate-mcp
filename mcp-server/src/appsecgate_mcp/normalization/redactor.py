"""Redactor — маскирует секреты до записи в БД (arch §4.9).

Инвариант №4 (AGENTS.md): redaction выполняется ДО записи в базу, а не
при отдаче. ``Redactor.redact_finding`` применяет политику по категориям
(§4.9): для категории ``secret`` snippet маскируется целиком; для прочих
категорий из snippet/message/metadata вычищаются вхождения известных
паттернов секретов и high-entropy-строк.

Сканеры (gitleaks, trufflehog) кладут сырой секрет в ``Finding.snippet``
(например ``item.Raw``) — поэтому ни один фрагмент не должен попасть в
``finding_context`` без прохождения через этот модуль.
"""

from __future__ import annotations

import base64
import binascii
import math
import re
from typing import Any

from appsecgate_mcp.models.finding import Category, Finding

REDACTED = "[REDACTED]"

# Паттерны известных секретов (§4.9): AWS / GCP / Azure, PEM, JWT.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # PEM-блоки (приватные ключи, сертификаты) — маскируем весь блок целиком.
    re.compile(r"-----BEGIN [A-Z0-9 ]+-----[\s\S]*?-----END [A-Z0-9 ]+-----", re.IGNORECASE),
    # Одинокая PEM-шапка, если блок обрезан сниппетом.
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ ?)?(?:PRIVATE KEY|CERTIFICATE)-----"),
    # AWS access key id (AKIA...) + secret access key (40 base64 символов).
    re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[A-Z0-9]{16}\b"),
    # GCP OAuth client secret (YA29...) и service account key.
    re.compile(r"\bYA29\.[0-9A-Za-z\-_]+"),
    # Azure connection string / shared key.
    re.compile(
        r"DefaultEndpointsProtocol=https?;AccountName=[^;]+;"
        r"AccountKey=[A-Za-z0-9+/=]+",
        re.IGNORECASE,
    ),
    # JWT (header.payload.signature).
    re.compile(r"\beyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]{16,}\b"),
    # Generic API-токены / ключи: «key=», «secret=», «password=».
    re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd)\b"
        r"\s*[=:]\s*[\"']?[A-Za-z0-9\-_+/=]{10,}",
    ),
]

# High-entropy: Shannon > 4.5 на строку длиной >= 16 (без пробелов/символов).
_ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9\-_+/=]{16,}")


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
    masked = _mask_high_entropy(masked)
    return masked


def _redact_metadata(value: Any) -> Any:
    """Рекурсивно маскирует секреты в произвольной метадате."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redact_metadata(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_metadata(v) for v in value)
    if isinstance(value, dict):
        return {k: _redact_metadata(v) for k, v in value.items()}
    return value


class Redactor:
    """Статeless-redactor: маскирует секреты в ``Finding`` до записи."""

    def redact_finding(self, finding: Finding) -> tuple[Finding, bool]:
        """Возвращает копию ``Finding`` с redacted snippet/message/metadata.

        Вторая часть кортежа — был ли хоть что-то замаскировано. Для
        категории ``secret`` snippet заменяется целиком (политика §4.9).
        """
        snippet = finding.snippet or ""
        if finding.category is Category.SECRET:
            masked_snippet = REDACTED
        else:
            masked_snippet = redact_text(snippet)

        message = finding.message or ""
        masked_message = redact_text(message)

        metadata = finding.metadata or {}
        masked_metadata = {k: _redact_metadata(v) for k, v in metadata.items()}

        redacted = (
            masked_snippet != snippet or masked_message != message or masked_metadata != metadata
        )

        redacted_finding = finding.model_copy(
            update={
                "snippet": masked_snippet,
                "message": masked_message,
                "metadata": masked_metadata,
            }
        )
        return redacted_finding, redacted


__all__ = ["Redactor", "REDACTED", "redact_text"]
