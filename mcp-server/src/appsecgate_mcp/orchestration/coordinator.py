"""Scan Coordinator — мозг оркестрации: план, параллельный запуск, нормализация.

Поток: определить доступные сканеры → запустить параллельно
(`asyncio.gather(..., return_exceptions=True)`) → нормализовать в `Finding`
с fingerprint → дедуплицировать → применить suppression → отсортировать.
Падение одного сканера изолируется: частичный результат важнее полной ошибки.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from appsecgate_mcp.config.models import Config
from appsecgate_mcp.models.finding import Finding, ScanMeta, ScannerError, ScanResult
from appsecgate_mcp.normalization.dedup import Deduplicator
from appsecgate_mcp.normalization.fingerprint import FingerprintGenerator
from appsecgate_mcp.normalization.normalizer import Normalizer
from appsecgate_mcp.normalization.redactor import Redactor
from appsecgate_mcp.normalization.suppress_filter import ConfigSuppressFilter
from appsecgate_mcp.scanners.base import RawFinding
from appsecgate_mcp.scanners.registry import ScannerRegistry
from appsecgate_mcp.storage.logical_id import compute_logical_id

logger = logging.getLogger(__name__)


class ScanCoordinator:
    """Оркестрирует запуск сканеров и пост-обработку находок."""

    def __init__(
        self,
        config: Config,
        registry: ScannerRegistry,
        *,
        suppression_store=None,
        shown_store=None,
        identity_store=None,
        context_store=None,
        project_root: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        # Корень проекта для приведения абсолютных путей сканеров к относительным.
        # None — пути не трогаем (совместимость с тестами без проекта).
        self.project_root = Path(project_root).resolve() if project_root else None
        # Проектная ось для записей identity/context. Заполняется сервером после
        # фиксации project_id в SessionState.initialize() (инвариант №6).
        self.project_id = project_id
        # Кэш содержимого исходников на один скан (file_path -> source).
        self._source_cache: dict[str, str] = {}
        self.normalizer = Normalizer(config)
        self.fingerprint = FingerprintGenerator()
        self.dedup = Deduplicator()
        self.suppress_filter = ConfigSuppressFilter(config)
        self.suppression_store = suppression_store
        self.shown_store = shown_store
        self.identity_store = identity_store
        self.context_store = context_store
        # Redaction секретов до записи в БД (инвариант №4).
        self.redactor = Redactor()

    async def scan(
        self, files: list[str], mode: str = "file", *, persist: bool = True
    ) -> ScanResult:
        """Сканирует файлы в режиме `file` | `diff` | `project`.

        ``persist=False`` — инвентаризация без записи в shown/identity/context
        (announce-only для ``scan_project``, arch §4.3): находки не помечаются
        ``SHOWN``.
        """
        started = datetime.now(UTC)
        t0 = time.perf_counter()
        # Сбрасываем кэш исходников: каждый скан читает актуальное состояние файлов.
        self._source_cache = {}
        rel_files = [self._to_relative(f) for f in files]
        scanned = [rel for rel in rel_files if rel is not None]
        logger.info("scan start mode=%s files=%s", mode, len(scanned))
        meta = ScanMeta(
            mode=mode,
            scanned_files=scanned,
            started_at=started.isoformat(),
        )
        outside = len(rel_files) - len(scanned)
        if outside:
            meta.warnings.append(f"excluded {outside} file(s) outside project root")

        available = await self._select_available(meta)
        logger.info(
            "scan mode=%s available=%s skipped=%s",
            mode,
            [s.name for s in available],
            meta.scanners_skipped,
        )
        raw_findings = await self._run_all(available, files, mode, meta)

        relative = self._relativize(raw_findings, meta)
        findings = [self._to_finding(rf) for rf in relative]
        findings = self.dedup.deduplicate(findings)
        findings = self.suppress_filter.apply(findings)
        findings = await self._apply_suppression(findings)
        findings = self.normalizer.process(findings)

        if persist:
            await self._record_shown(findings, meta)

        meta.finished_at = datetime.now(UTC).isoformat()
        meta.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(
            "scan done mode=%s findings=%s duration_ms=%s errors=%s",
            mode,
            len(findings),
            meta.duration_ms,
            [e.model_dump() for e in meta.errors],
        )
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

    async def _run_all(
        self, scanners: list, files: list[str], mode: str, meta: ScanMeta
    ) -> list[RawFinding]:
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
            # Частичные результаты сканера (пропущенные пакеты и т.п.) — в meta.
            meta.warnings.extend(getattr(scanner, "warnings", []))
            raw.extend(result)
        return raw

    def _relativize(self, raw_findings: list[RawFinding], meta: ScanMeta) -> list[RawFinding]:
        """Приводит file_path к относительному виду; вне корня проекта — исключает.

        Вызывается до `_to_finding`, чтобы fingerprint считался от относительного пути
        и не зависел от места монтирования проекта (локально, Docker, CI).
        """
        if self.project_root is None:
            return raw_findings
        result: list[RawFinding] = []
        outside = 0
        for rf in raw_findings:
            rel = self._to_relative(rf.file_path)
            if rel is None:
                outside += 1
                continue
            if rel != rf.file_path:
                rf = replace(rf, file_path=rel)
            result.append(rf)
        if outside:
            meta.warnings.append(f"excluded {outside} finding(s) outside project root")
        return result

    def _to_relative(self, path: str) -> str | None:
        """Абсолютный путь внутри корня -> относительный POSIX; вне корня -> None."""
        if not path:
            return path
        candidate = Path(path)
        if not candidate.is_absolute():
            return os.path.normpath(candidate.as_posix())
        root = self.project_root
        if root is None:
            # Без корня проекта относительность не определить: путь не трогаем.
            return path
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            try:
                return candidate.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                return None

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
        if not findings:
            return
        if self.shown_store is None and self.context_store is None and self.identity_store is None:
            return
        try:
            await self._persist_findings(findings)
        except Exception as exc:  # журнал не критичен для выдачи результата
            meta.warnings.append(f"stores write failed: {exc}")

    async def _source_for(self, file_path: str) -> str:
        """Читает исходник файла из корня проекта (монтируется :ro).

        Возвращает ``""``, если корня нет, путь выходит за его пределы,
        файл отсутствует или его нельзя прочитать — тогда ``logical_id``
        упадёт на bucket по строкам (см. §4.8).
        """
        if not file_path or self.project_root is None:
            return ""
        if file_path in self._source_cache:
            return self._source_cache[file_path]
        candidate = Path(file_path)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(self.project_root)
            except ValueError:
                return ""
        target = self.project_root / candidate
        source = ""
        try:
            if target.is_file():
                source = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            source = ""
        self._source_cache[file_path] = source
        return source

    async def _persist_findings(self, findings: list[Finding]) -> None:
        """Проставляет ``logical_id`` и пишет в shown/identity/context.

        Redaction выполняется здесь, до любой записи в БД (инвариант №4):
        в ``shown_findings`` уходит только ``logical_id``, в
        ``finding_context`` — уже замаскированные snippet/message/metadata.
        """
        shown_store = self.shown_store
        identity_store = self.identity_store
        context_store = self.context_store

        logical_ids: dict[str, str] = {}
        identity_rows: list[tuple[Finding, str]] = []
        context_rows: list[tuple[Finding, str]] = []

        for finding in findings:
            source = await self._source_for(finding.file_path)
            logical_id = compute_logical_id(
                finding.rule_id, finding.file_path, finding.line_start, source
            )
            logical_ids[finding.fingerprint] = logical_id

            if identity_store is not None:
                identity_rows.append((finding, logical_id))

            if context_store is not None:
                # Redaction строго до записи в finding_context (инвариант №4).
                redacted, _ = self.redactor.redact_finding(finding)
                context_rows.append((redacted, logical_id))

        if shown_store is not None:
            await shown_store.record_shown_batch(findings, logical_ids=logical_ids)

        if identity_store is not None:
            if self.project_id is None:
                raise RuntimeError("identity_store set without project_id")
            for finding, logical_id in identity_rows:
                await identity_store.upsert(
                    self.project_id,
                    logical_id,
                    finding.rule_id,
                    finding.file_path,
                    finding.fingerprint,
                )

        if context_store is not None:
            if self.project_id is None:
                raise RuntimeError("context_store set without project_id")
            for finding, logical_id in context_rows:
                await context_store.upsert(self.project_id, logical_id, finding)
