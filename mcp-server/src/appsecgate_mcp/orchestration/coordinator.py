"""Scan Coordinator — мозг оркестрации: план, параллельный запуск, нормализация.

Поток: определить доступные сканеры → запустить параллельно
(`asyncio.gather(..., return_exceptions=True)`) → нормализовать в `Finding`
с fingerprint → дедуплицировать → применить suppression → отсортировать.
Падение одного сканера изолируется: частичный результат важнее полной ошибки.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from appsecgate_mcp.config.models import Config
from appsecgate_mcp.models.finding import Finding, ScanMeta, ScannerError, ScanResult
from appsecgate_mcp.normalization.dedup import Deduplicator
from appsecgate_mcp.normalization.fingerprint import FingerprintGenerator
from appsecgate_mcp.normalization.normalizer import Normalizer
from appsecgate_mcp.scanners.base import RawFinding
from appsecgate_mcp.scanners.registry import ScannerRegistry


class ScanCoordinator:
    """Оркестрирует запуск сканеров и пост-обработку находок."""

    def __init__(
        self,
        config: Config,
        registry: ScannerRegistry,
        *,
        suppression_store=None,
        shown_store=None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.normalizer = Normalizer(config)
        self.fingerprint = FingerprintGenerator()
        self.dedup = Deduplicator()
        self.suppression_store = suppression_store
        self.shown_store = shown_store

    async def scan(self, files: list[str], mode: str = "file") -> ScanResult:
        """Сканирует файлы в режиме `file` | `diff` | `project`."""
        started = datetime.now(UTC)
        t0 = time.perf_counter()
        meta = ScanMeta(
            mode=mode,
            scanned_files=list(files),
            started_at=started.isoformat(),
        )

        available = await self._select_available(meta)
        raw_findings = await self._run_all(available, files, mode, meta)

        findings = [self._to_finding(rf) for rf in raw_findings]
        findings = self.dedup.deduplicate(findings)
        findings = await self._apply_suppression(findings)
        findings = self.normalizer.process(findings)

        await self._record_shown(findings, meta)

        meta.finished_at = datetime.now(UTC).isoformat()
        meta.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        return ScanResult(findings=findings, meta=meta)

    async def _select_available(self, meta: ScanMeta) -> list:
        """Оставляет сканеры, чьи бинарники доступны; остальные — в skipped."""
        available = []
        for scanner in self.registry.all():
            try:
                ok = await scanner.is_available()
            except Exception:  # изоляция: недоступность != падение координатора
                ok = False
            if ok:
                available.append(scanner)
            else:
                meta.scanners_skipped.append(scanner.name)
        return available

    async def _run_all(self, scanners: list, files: list[str], mode: str, meta: ScanMeta) -> list[RawFinding]:
        """Параллельно запускает сканеры, изолируя исключения."""
        if not scanners:
            return []
        tasks = [scanner.scan(files, mode) for scanner in scanners]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        raw: list[RawFinding] = []
        for scanner, result in zip(scanners, results, strict=True):
            if isinstance(result, BaseException):
                meta.errors.append(ScannerError(scanner=scanner.name, error=str(result)))
                continue
            meta.scanners_ran.append(scanner.name)
            raw.extend(result)
        return raw

    def _to_finding(self, raw: RawFinding) -> Finding:
        fp = self.fingerprint.generate_for(raw.rule_id, raw.file_path, raw.snippet)
        return raw.to_finding(fingerprint=fp)

    async def _apply_suppression(self, findings: list[Finding]) -> list[Finding]:
        if self.suppression_store is None:
            return findings
        try:
            return await self.suppression_store.filter_active(findings)
        except Exception:
            return findings

    async def _record_shown(self, findings: list[Finding], meta: ScanMeta) -> None:
        if self.shown_store is None or not findings:
            return
        try:
            await self.shown_store.record_shown_batch(findings)
        except Exception as exc:  # журнал не критичен для выдачи результата
            meta.warnings.append(f"shown_store write failed: {exc}")
