"""Дедупликация находок между сканерами.

Одинаковые проблемы могут давать разные сканеры (например, Gitleaks и
TruffleHog могут найти один и тот же hardcoded secret). Дубликаты
схлопываются по (file_path, line_start); среди дубликатов остаётся
находка с наибольшей severity. Выбор «выжившего» детерминирован
(ADR-0001 §3.2): порядок поступления raw-находок не влияет на результат.

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

# Каноническая длина семейного ключа секрета. Gitleaks обрезает Secret по
# паттерну правила (github-pat: «ghp_» + 36 символов), другие правила/сканеры
# отдают полное значение — один и тот же токен даёт разные Secret. Сводим
# семейный ключ к фиксированному префиксу (план §5 / T1; E2E-2026-10-30).
_FAMILY_SECRET_PREFIX = 40

# Приоритет сканеров при выборе «выжившего» (ADR-0001 §3.2): чем меньше,
# тем находка предпочтительнее как каноническая. Gitleaks точнее по rule_id
# для секретов, поэтому его находка побеждает при равном severity.
SCANNER_PRIORITY: dict[str, int] = {
    "gitleaks": 0,
    "trufflehog": 1,
    "semgrep": 2,
    "trivy": 3,
}

# Внутри Gitleaks конкретные паттерны приоритетнее generic.
RULE_PRIORITY: dict[str, int] = {
    "github-pat": 0,
    "aws-access-key": 0,
    "private-key": 0,
    "generic-api-key": 10,
}


def _stable_sort_key(finding: Finding) -> tuple:
    """Стабильный ключ сортировки находок (ADR-0001 §3.2).

    Порядок (по возрастанию): severity (CRITICAL раньше всех) → приоритет
    сканера → приоритет правила → rule_id лексикографически. Не зависит от
    порядка поступления raw-находок, поэтому «выживший» детерминирован.
    """
    return (
        -SEVERITY_ORDER.get(finding.severity, 0),
        SCANNER_PRIORITY.get(finding.scanner, 99),
        RULE_PRIORITY.get(finding.rule_id, 50),
        finding.rule_id,
    )


def _canonical_secret(value: str) -> str:
    """Каноническое «тело» секрета: без кавычек, усечено до префикса.

    Gitleaks правила с `secretGroup` обрезают значение (github-pat: фиксированная
    длина паттерна); одно значение, найденное разными правилами, должно давать
    один семейный ключ (план §5, T1).
    """
    clean = value.strip().strip("\"'")
    if len(clean) > _FAMILY_SECRET_PREFIX:
        clean = clean[:_FAMILY_SECRET_PREFIX]
    return normalize_snippet(clean)


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
            return _canonical_secret(secret)
    value = normalize_snippet(finding.snippet)
    if not value:
        return f"{_NO_BODY_PREFIX}{finding.fingerprint}"
    return value


class Deduplicator:
    """Убирает находки-дубликаты разных сканеров в одном файле."""

    def deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """Уровень 1: кросс-сканерные дубликаты на одной строке.

        Если два РАЗНЫХ сканера дали находку в одной строке — это, скорее
        всего, одна проблема (например, секрет от Gitleaks и TruffleHog):
        остаётся находка с большей severity, при равной — по приоритету
        сканера/правила (детерминированно, ADR-0001 §3.2).

        Находки одного сканера на одной строке НЕ схлопываем: это разные
        проблемы (например, все CVE из Trivy в одном lock-файле имеют
        `line_start=1` — T13). Их «семьи» по телу проблемы склеивает уровень 2
        (`deduplicate_families`).
        """
        groups: dict[tuple[str, int], list[Finding]] = {}
        for f in findings:
            groups.setdefault((f.file_path, f.line_start), []).append(f)

        result: list[Finding] = []
        for group in groups.values():
            if len({f.scanner for f in group}) > 1:
                # Кросс-сканерный дубликат: выживает лучший в детерминированном порядке.
                result.append(min(group, key=_stable_sort_key))
            else:
                # Один сканер: каждая находка на строке — отдельная проблема (T13).
                result.extend(sorted(group, key=_stable_sort_key))
        return result

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

    @classmethod
    def _collapse(cls, findings: list[Finding], *, key) -> list[Finding]:
        """Общая логика: первый в детерминированном порядке побеждает.

        Вход сортируется по ``_stable_sort_key``; по каждому ключу ``key``
        остаётся первая находка — она же наилучшая по severity/сканеру/
        правилу. Результат не зависит от порядка поступления raw-находок
        (фикс T10, ADR-0001 §3.2).
        """
        seen: dict[tuple, Finding] = {}
        for finding in sorted(findings, key=_stable_sort_key):
            k = key(finding)
            if k not in seen:
                seen[k] = finding
        return list(seen.values())
