"""Адаптер Trivy — SCA, IaC, лицензии.

`trivy fs` сканирует файловую систему: уязвимости зависимостей (vuln),
мисконфигурации IaC (misconfig) и лицензии (license). Работает по корню
проекта, результат фильтруется до переданных файлов.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from appsecgate_mcp.config.models import ScannerConfig
from appsecgate_mcp.models.finding import Category
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.runner import ScannerExecutionError

# Целевые файлы для SCA/IaC, когда координатор передаёт конкретный список.
_TARGET_NAMES: frozenset[str] = frozenset(
    {
        "requirements.txt",
        "poetry.lock",
        "pipfile.lock",
        "pipfile",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "go.mod",
        "go.sum",
        "cargo.lock",
        "gemfile.lock",
        "composer.lock",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
    }
)
_TARGET_SUFFIXES: frozenset[str] = frozenset({".tf", ".yaml", ".yml"})


class TrivyAdapter(BaseScanner):
    """Обёртка над Trivy CLI (`trivy fs`)."""

    name = "trivy"
    category = Category.SCA
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

    @property
    def _cache_dir(self) -> str:
        return os.environ.get("TRIVY_CACHE_DIR", "/home/appsecgate/.cache/trivy")

    async def is_available(self) -> bool:
        try:
            result = await self.run(["trivy", "--version"])
        except ScannerExecutionError:
            return False
        return result.returncode == 0

    def _is_target(self, path: str) -> bool:
        p = Path(path)
        if p.is_dir():
            return True
        name = p.name.lower()
        if name in _TARGET_NAMES:
            return True
        return p.suffix.lower() in _TARGET_SUFFIXES

    async def scan(self, files: list[str], mode: str) -> list[RawFinding]:
        source = self.scan_source(files, mode)
        cmd = [
            "trivy",
            "fs",
            "--format",
            "json",
            "--quiet",
            "--scanners",
            "vuln,misconfig,license",
            "--cache-dir",
            self._cache_dir,
            "--skip-db-update",
            "--skip-java-db-update",
            source,
        ]
        result = await self.run(cmd)
        if result.returncode != 0:
            return []
        findings = self._parse(result.stdout)
        if mode == "project" or not files:
            return findings
        allowed = {self.normalize_path(f) for f in files}
        return [f for f in findings if self.normalize_path(f.file_path) in allowed]

    def _parse(self, stdout: str) -> list[RawFinding]:
        if not stdout.strip():
            return []
        try:
            data: dict[str, Any] = json.loads(stdout)
        except json.JSONDecodeError:
            return []

        findings: list[RawFinding] = []
        for res in data.get("Results", []) or []:
            target = str(res.get("Target") or "")
            findings.extend(self._parse_vulns(res, target))
            findings.extend(self._parse_misconfigs(res, target))
            findings.extend(self._parse_licenses(res, target))
        return findings

    def _parse_vulns(self, res: dict[str, Any], target: str) -> list[RawFinding]:
        out: list[RawFinding] = []
        for v in res.get("Vulnerabilities", []) or []:
            fixed = v.get("FixedVersion")
            remediation = f"Upgrade {v.get('PkgName')} to {fixed}" if fixed else None
            out.append(
                RawFinding(
                    rule_id=str(v.get("VulnerabilityID") or "trivy-vuln"),
                    raw_severity=str(v.get("Severity") or "unknown"),
                    file_path=target,
                    scanner=self.name,
                    message=str(
                        v.get("Title") or v.get("Description") or v.get("VulnerabilityID") or ""
                    ),
                    category=Category.SCA,
                    metadata={
                        "package": v.get("PkgName"),
                        "installed_version": v.get("InstalledVersion"),
                        "fixed_version": fixed,
                        "primary_url": v.get("PrimaryURL"),
                    },
                    remediation=remediation,
                )
            )
        return out

    def _parse_misconfigs(self, res: dict[str, Any], target: str) -> list[RawFinding]:
        out: list[RawFinding] = []
        for m in res.get("Misconfigurations", []) or []:
            cause = m.get("CauseMetadata", {}) or {}
            line_start = int(cause.get("StartLine") or 1)
            line_end = int(cause.get("EndLine") or line_start)
            out.append(
                RawFinding(
                    rule_id=str(m.get("ID") or "trivy-misconfig"),
                    raw_severity=str(m.get("Severity") or "unknown"),
                    file_path=target,
                    scanner=self.name,
                    line_start=line_start,
                    line_end=line_end,
                    message=str(m.get("Message") or m.get("Title") or ""),
                    snippet=str(cause.get("Code", {}).get("Lines", [{}])[0].get("Content", ""))
                    if isinstance(cause.get("Code"), dict)
                    else "",
                    category=Category.IAC,
                    metadata={"title": m.get("Title"), "references": m.get("References", [])},
                    remediation=m.get("Resolution"),
                )
            )
        return out

    def _parse_licenses(self, res: dict[str, Any], target: str) -> list[RawFinding]:
        out: list[RawFinding] = []
        for lic in res.get("Licenses", []) or []:
            out.append(
                RawFinding(
                    rule_id=f"license-{lic.get('Name', 'unknown')}",
                    raw_severity=str(lic.get("Severity") or "low"),
                    file_path=str(lic.get("FilePath") or target),
                    scanner=self.name,
                    message=f"License: {lic.get('Name', 'unknown')} ({lic.get('Category', 'unknown')})",
                    category=Category.LICENSE,
                    metadata={"license": lic.get("Name"), "category": lic.get("Category")},
                )
            )
        return out
