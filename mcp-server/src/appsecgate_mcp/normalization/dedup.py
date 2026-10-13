"""Дедупликация находок между сканерами.

Одинаковые проблемы могут давать разные сканеры (например, Gitleaks и
TruffleHog могут найти один и тот же hardcoded secret). Дубликаты
схлопываются по (file_path, line_start); среди дубликатов остаётся
находка с наибольшей severity (tie-break — первая встреченная).

Дополнительно схлопываются «семьи» проблем — находки разных сканеров и
правил, которые описывают одну и ту же проблему (одно значение секрета
или один и тот же фрагмент кода в одном окне строк), но с разными
rule_id (src: `docs/open-tasks.md`, задача T1).
"""

from __future__ import annotations

from appsecgate_mcp.models.finding import SEVERITY_ORDER, Category, Finding
from appsecgate_mcp.normalization.fingerprint import normalize_snippet

# Окно строк для «семейного» дедупа второго уровня (строки в одном окне
# длиной 20 считаются «рядом» — ровно как bucket в logical_id, §4.8).
_FAMILY_BUCKET = 20

# Префикс для ключей без тела проблемы: такие находки не схлопываем.
_NO_BODY_PREFIX = "\x00"


def _family_value(finding: Finding) -> str:
    """Каноническое «тело проблемы» без учёта rule_id/сканера.

    Для секретов предпочитаем извлечённое значение (`metadata.Secret` —
    Gitleaks); TruffleHog кладёт raw-значение в сниппет, поэтому сниппет —
    fallback. Для остальных категорий — нормализованный сниппет: два
    semgrep-правила, сработавших на один и тот же текст, дают один ключ.

    Если тела нет (пустой текст) — возвращает уникальный ключ, чтобы
    находку без информации о содержании НЕ схлопывали.
    """
    if finding.category is Category.SECRET:
        secret = finding.metadata.get("Secret")
        if isinstance(secret, str) and secret.strip():
            return normalize_snippet(secret)
    value = normalize_snippet(finding.snippet)
    if not value:
        return f"{_NO_BODY_PREFIX}{finding.fingerprint}"
    return value


class Deduplicator:
    """Убирает находки-дубликаты разных сканеров в одном файле."""

    def deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """Уровень 1: ключ — точная пара (file_path, line_start).

        Если два сканера дали находку в одной строке, остаётся находка
        с большей severity; при равной severity — первая по порядку
        сканеров-приоритетов.
        """
        return self._collapse(findings, key=lambda f: (f.file_path, f.line_start))

    def deduplicate_families(self, findings: list[Finding]) -> list[Finding]:
        """Уровень 2: ключ — (file_path, окно строк, тело проблемы).

        Схлопывает находки разных сканеров/правил, описывающие одну и ту же
        проблему: одно значение секрета (`metadata.Secret` / сниппет) или
        один и тот же нормализованный фрагмент в том же окне строк.
        `rule_id` и `scanner` в ключ не входят — Gitleaks и TruffleHog на
        одном секрете дают разные rule_id, но одну «семью». Находки без
        тела проблемы (пустой сниппет) не трогаем.
        """
        return self._collapse(
            findings,
            key=lambda f: (f.file_path, f.line_start // _FAMILY_BUCKET, _family_value(f)),
        )

    @staticmethod
    def _collapse(findings: list[Finding], *, key) -> list[Finding]:
        """Общая логика: первый встреченный побеждает, больший severity — раньше."""
        seen: dict[tuple, Finding] = {}
        for finding in findings:
            k = key(finding)
            existing = seen.get(k)
            if existing is None:
                seen[k] = finding
            elif SEVERITY_ORDER.get(finding.severity, 0) > SEVERITY_ORDER.get(existing.severity, 0):
                seen[k] = finding
        return list(seen.values())
