"""Адаптер TruffleHog — поиск секретов (дополняет Gitleaks).

TruffleHog `filesystem` пишет JSONL: по одному JSON-объекту на строку.
Парсим построчно; файл берём из `SourceMetadata.Data.Filesystem.file`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from secgate_mcp.config.models import ScannerConfig
from secgate_mcp.models.finding import Category
from secgate_mcp.scanners.base import BaseScanner, RawFinding
from secgate_mcp.scanners.runner import ScannerExecutionError


class TruffleHogAdapter(BaseScanner):
    """Обёртка над TruffleHog CLI (`trufflehog filesystem`)."""

    name = "trufflehog"
    category = Category.SECRET
    supported_languages = frozenset()

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
            result = await self.run(["trufflehog", "--version"])
        except ScannerExecutionError:
            return False
        return result.returncode == 0

    async def scan(self, files: list[str], mode: str) -> list[RawFinding]:
        source = self.scan_source(files, mode)
        cmd = ["trufflehog", "filesystem", "--json", "--no-update", source]
        if mode != "project" and files:
            cmd += ["--include-paths", ",".join(files)]
        result = await self.run(cmd)
        # TruffleHog пишет результаты в stdout даже при ненулевом коде.
        if result.returncode not in (0, 1, 183):
            return []
        return self._parse(result.stdout)

    @staticmethod
    def _norm(path: str) -> str:
        return str(Path(path)).lstrip("./")

    def _parse(self, stdout: str) -> list[RawFinding]:
        findings: list[RawFinding] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item: Any = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue

            file_path = self._extract_path(item)
            line_no = self._extract_line(item)
            detector = str(item.get("DetectorName") or "trufflehog")
            verified = bool(item.get("Verified"))
            findings.append(
                RawFinding(
                    rule_id=detector,
                    raw_severity="high" if verified else "medium",
                    file_path=file_path,
                    scanner=self.name,
                    line_start=line_no,
                    line_end=line_no,
                    message=f"{detector} secret detected"
                    + (" (verified)" if verified else " (unverified)"),
                    snippet=str(item.get("Raw") or ""),
                    category=Category.SECRET,
                    metadata={
                        "verified": verified,
                        "detector_type": item.get("DetectorType"),
                        "decoder": item.get("DecoderName"),
                    },
                    remediation="Rotate the leaked credential and remove it from history.",
                )
            )
        return findings

    @staticmethod
    def _extract_path(item: dict[str, Any]) -> str:
        meta = item.get("SourceMetadata", {}) or {}
        data = meta.get("Data", {}) or {}
        fs = data.get("Filesystem", {}) or {}
        return str(fs.get("file") or data.get("file") or "")

    @staticmethod
    def _extract_line(item: dict[str, Any]) -> int:
        meta = item.get("SourceMetadata", {}) or {}
        data = meta.get("Data", {}) or {}
        fs = data.get("Filesystem", {}) or {}
        return int(fs.get("line") or 1)
