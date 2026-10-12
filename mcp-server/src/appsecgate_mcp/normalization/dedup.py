"""Дедупликация находок между сканерами.

Одинаковые проблемы могут давать разные сканеры (например, Gitleaks и
TruffleHog могут найти один и тот же hardcoded secret). Дубликаты
схлопываются по (file_path, line_start); среди дубликатов остаётся
находка с наибольшей severity (tie-break — первая встреченная).
"""

from __future__ import annotations

from appsecgate_mcp.models.finding import SEVERITY_ORDER, Finding


class Deduplicator:
    """Убирает находки-дубликаты разных сканеров в одном файле."""

    def deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """Возвращает список без дубликатов.

        Ключ — (file_path, line_start). Если два сканера дали находку
        в одной строке, остаётся находка с большей severity; при равной
        severity — первая по порядку сканеров-приоритетов.
        """
        seen: dict[tuple[str, int], Finding] = {}
        for finding in findings:
            key = (finding.file_path, finding.line_start)
            existing = seen.get(key)
            if existing is None:
                seen[key] = finding
            elif SEVERITY_ORDER.get(finding.severity, 0) > SEVERITY_ORDER.get(existing.severity, 0):
                seen[key] = finding
        return list(seen.values())
