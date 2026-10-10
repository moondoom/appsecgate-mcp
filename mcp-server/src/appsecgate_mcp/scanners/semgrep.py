"""Адаптер Semgrep — SAST-сканер.

Запускает `semgrep --json` на переданных файлах и парсит результат в
`RawFinding`. Без shell, с таймаутом из `BaseScanner`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from appsecgate_mcp.config.models import ScannerConfig
from appsecgate_mcp.models.finding import Category
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.runner import ScannerExecutionError

# Расширения, которые имеет смысл отдавать Semgrep.
_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
        ".java", ".kt", ".kts", ".go", ".rb", ".php", ".c", ".h",
        ".cc", ".cpp", ".hpp", ".cs", ".rs", ".swift", ".scala",
        ".tf", ".hcl", ".yaml", ".yml", ".json",
    }
)

# semgrep-core в ряде сборок отдаёт этот плейсхолдер вместо реального кода
# (проверяется через `strings semgrep-core | grep 'requires login'`). Если
# положить его в snippet, fingerprint вырождается в константу, и все находки
# одного правила в одном файле схлопываются в один ID.
_PLACEHOLDER_SNIPPETS: frozenset[str] = frozenset({"requires login"})


def _is_placeholder_snippet(text: str) -> bool:
    """True, если сканер вернул заглушку вместо настоящего фрагмента кода."""
    return text.strip().lower() in _PLACEHOLDER_SNIPPETS


class SemgrepAdapter(BaseScanner):
    """Обёртка над Semgrep CLI."""

    name = "semgrep"
    category = Category.SAST
    supported_languages = frozenset(
        {
            "python", "javascript", "typescript", "java", "go", "ruby", "php",
            "c", "cpp", "csharp", "rust", "kotlin", "scala", "swift", "hcl",
        }
    )
    default_rulesets: tuple[str, ...] = ("p/security-audit",)

    def __init__(
        self,
        *,
        project_path: str | None = None,
        timeout: float | int = 120,
        config: ScannerConfig | None = None,
    ) -> None:
        super().__init__(project_path=project_path, timeout=timeout)
        self.config = config

    def _rulesets(self) -> list[str]:
        if self.config is not None and self.config.rulesets:
            return list(self.config.rulesets)
        return list(self.default_rulesets)

    async def is_available(self) -> bool:
        try:
            result = await self.run(["semgrep", "--version"])
        except ScannerExecutionError:
            return False
        return result.returncode == 0

    def _is_supported(self, path: str) -> bool:
        p = Path(path)
        if p.is_dir():
            return True
        return p.suffix.lower() in _SUPPORTED_EXTENSIONS

    def _select_targets(self, files: list[str], mode: str) -> list[str]:
        if mode == "project":
            return list(files)
        return [f for f in files if self._is_supported(f)]

    async def scan(self, files: list[str], mode: str) -> list[RawFinding]:
        targets = self._select_targets(files, mode)
        if not targets:
            return []

        cmd: list[str] = [
            "semgrep",
            "--json",
            "--quiet",
            "--no-git-ignore",
            "--metrics=off",
            "--jobs",
            "1",
        ]
        for ruleset in self._rulesets():
            cmd += ["--config", ruleset]
        cmd += ["--"] + targets

        result = await self.run(cmd)
        # Semgrep возвращает 0 (нет находок) или 1 (есть находки). Прочее — ошибка.
        if result.returncode not in (0, 1):
            return []
        return self._parse(result.stdout)

    def _parse(self, stdout: str) -> list[RawFinding]:
        if not stdout.strip():
            return []
        try:
            data: dict[str, Any] = json.loads(stdout)
        except json.JSONDecodeError:
            return []

        findings: list[RawFinding] = []
        for item in data.get("results", []) or []:
            extra = item.get("extra", {}) or {}
            meta = extra.get("metadata", {}) or {}
            start = item.get("start", {}) or {}
            end = item.get("end", {}) or {}
            file_path = str(item.get("path") or "")
            line_start = int(start.get("line", 1) or 1)
            line_end = int(end.get("line", line_start) or line_start)
            severity = extra.get("severity") or meta.get("severity") or "info"

            # semgrep-core может вернуть плейсхолдер вместо кода — тогда
            # подтягиваем реальные строки из файла, иначе fingerprint выродится.
            raw_lines = extra.get("lines")
            snippet = str(raw_lines) if raw_lines else ""
            if not snippet.strip() or _is_placeholder_snippet(snippet):
                snippet = self._read_snippet(file_path, line_start, line_end)

            scanner_fp = extra.get("fingerprint")
            if not scanner_fp or (
                isinstance(scanner_fp, str) and _is_placeholder_snippet(scanner_fp)
            ):
                scanner_fp = None

            findings.append(
                RawFinding(
                    rule_id=str(item.get("check_id") or "semgrep"),
                    raw_severity=str(severity),
                    file_path=file_path,
                    scanner=self.name,
                    line_start=line_start,
                    line_end=line_end,
                    message=str(extra.get("message") or meta.get("message") or ""),
                    snippet=snippet,
                    category=Category.SAST,
                    metadata={
                        "fingerprint": scanner_fp,
                        "references": meta.get("references", []),
                        "cwe": meta.get("cwe"),
                        "owasp": meta.get("owasp"),
                        "confidence": meta.get("confidence"),
                    },
                    remediation=meta.get("fix"),
                )
            )
        return findings

    def _read_snippet(self, file_path: str, line_start: int, line_end: int) -> str:
        """Читает реальные строки файла, когда сканер вернул заглушку/пусто.

        Путь может быть относительным — тогда он разрешается от project_path.
        Любые ошибки чтения не должны ронять скан: возвращаем пустую строку.
        """
        if not file_path:
            return ""
        path = Path(file_path)
        if not path.is_absolute():
            path = Path(self.project_path) / path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        lines = text.splitlines()
        if not lines:
            return ""
        start = max(line_start, 1)
        end = min(line_end, len(lines))
        if start > len(lines):
            return ""
        return "\n".join(lines[start - 1 : end])
