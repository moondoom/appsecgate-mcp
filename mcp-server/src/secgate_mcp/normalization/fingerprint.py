"""FingerprintGenerator — детерминированный ID находки.

Назначение: сопоставление находки между локальным и CI-сканом.
Требование: стабилен при сдвигах строк, уникален для разных проблем.

Подход (из architecture.md §3.4):
  fingerprint = sha256(rule_id + file_path + normalize_snippet(snippet))[:16]

Номер строки намеренно НЕ входит в ключ: при сдвиге кода находка
останется той же самой.
"""

from __future__ import annotations

import hashlib
import re

from secgate_mcp.models.finding import Finding

_COMMENT_RE = re.compile(r"\s*(?://|#|/\*|<!--|--).*$", re.MULTILINE)
_WS_RE = re.compile(r"\s+")


def normalize_snippet(snippet: str) -> str:
    """Нормализует фрагмент кода для устойчивого хэша.

    Шаги:
      1. Обрезаем пробелы по краям.
      2. Вырезаем однострочные комментарии и открытия блочных.
      3. Схлопываем множественные пробелы/переводы в один пробел.
      4. Приводим к нижнему регистру.
    """
    if not snippet:
        return ""
    text = snippet.strip()
    text = _COMMENT_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    return text.strip().lower()


class FingerprintGenerator:
    """Генерирует 16-символьный hex-fingerprint из rule_id + file + snippet."""

    def __init__(self, length: int = 16) -> None:
        self.length = length

    def generate(self, finding: Finding) -> str:
        """Вычисляет fingerprint для нормализованной находки."""
        normalized = normalize_snippet(finding.snippet)
        key = f"{finding.rule_id}:{finding.file_path}:{normalized}"
        digest = hashlib.sha256(key.encode()).hexdigest()
        return digest[: self.length]

    def generate_for(self, rule_id: str, file_path: str, snippet: str) -> str:
        """Генерирует fingerprint без полноценного объекта Finding (для тестов)."""
        normalized = normalize_snippet(snippet)
        key = f"{rule_id}:{file_path}:{normalized}"
        return hashlib.sha256(key.encode()).hexdigest()[: self.length]
