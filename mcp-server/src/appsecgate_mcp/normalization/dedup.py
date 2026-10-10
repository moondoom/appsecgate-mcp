"""Дедупликация находок между сканерами.

Одинаковые проблемы могут давать разные сканеры (например, Gitleaks и
TruffleHog могут найти один и тот же hardcoded secret). Дубликаты
схлопываются по (rule_id, file_path, line_start) с приоритетом более
информативного сканера.
"""

from __future__ import annotations

from appsecgate_mcp.models.finding import Finding


class Deduplicator:
    """Убирает находки-дубликаты разных сканеров в одном файле."""

    def deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """Возвращает список без дубликатов.

        Ключ — (file_path, line_start). Если два сканера дали находку
        в одной строке, остаётся первая (по порядку сканеров-приоритетов).
        """
        seen: dict[tuple[str, int], Finding] = {}
        for finding in findings:
            key = (finding.file_path, finding.line_start)
            if key not in seen:
                seen[key] = finding
        return list(seen.values())
