"""Адаптер Gitleaks — поиск секретов.

Gitleaks лучше работает по директории, чем по отдельным файлам, поэтому
адаптер сканирует проект целиком (без git) и фильтрует результат до
переданного набора файлов.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from appsecgate_mcp.config.models import ScannerConfig
from appsecgate_mcp.models.finding import Category
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.runner import ScannerExecutionError


class GitleaksAdapter(BaseScanner):
    """Обёртка над Gitleaks CLI (`gitleaks detect`)."""

    name = "gitleaks"
    category = Category.SECRET
    supported_languages = frozenset()  # секреты не привязаны к языку

    def __init__(
        self,
        *,
        project_path: str | None = None,
        timeout: float | int = 120,
        config: ScannerConfig | None = None,
    ) -> None:
        super().__init__(project_path=project_path, timeout=timeout)
        self.config = config

    async def is_available(self) -> bool:
        try:
            result = await self.run(["gitleaks", "version"])
        except ScannerExecutionError:
            return False
        return result.returncode == 0

    async def scan(self, files: list[str], mode: str) -> list[RawFinding]:
        source = self.scan_source(files, mode)
        cmd = [
            "gitleaks", "detect",
            "--no-git",
            "--no-banner",
            "--source", source,
            "--report-format", "json",
            "--report-path", "/dev/stdout",
            "--exit-code", "0",
        ]
        result = await self.run(cmd)
        # Gitleaks: 0 — успех (независимо от находок при --exit-code 0).
        if result.returncode != 0:
            return []
        findings = self._parse(result.stdout)
        if mode == "project" or not files:
            return findings
        allowed = {self._norm(f) for f in files}
        return [f for f in findings if self._norm(f.file_path) in allowed]

    @staticmethod
    def _norm(path: str) -> str:
        return str(Path(path)).lstrip("./")

    def _parse(self, stdout: str) -> list[RawFinding]:
        if not stdout.strip():
            return []
        try:
            data: Any = json.loads(stdout)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []

        findings: list[RawFinding] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            line_start = int(item.get("StartLine") or 1)
            line_end = int(item.get("EndLine") or line_start)
            match = item.get("Match") or item.get("Secret") or ""
            findings.append(
                RawFinding(
                    rule_id=str(item.get("RuleID") or "gitleaks"),
                    raw_severity="high",
                    file_path=str(item.get("File") or ""),
                    scanner=self.name,
                    line_start=line_start,
                    line_end=line_end,
                    message=str(item.get("Description") or item.get("RuleID") or "secret detected"),
                    snippet=str(match),
                    category=Category.SECRET,
                    metadata={
                        "entropy": item.get("Entropy"),
                        "tags": item.get("Tags", []),
                        "commit": item.get("Commit"),
                        "author": item.get("Author"),
                        "fingerprint": item.get("Fingerprint"),
                    },
                    remediation="Rotate the leaked credential and remove it from history.",
                )
            )
        return findings
