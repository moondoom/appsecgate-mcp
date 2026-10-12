"""MCP Server Layer — FastMCP-сервер AppSecGate (Фаза 1).


Регистрирует MCP-инструменты, обслуживает stdio и
streamable-http транспорты (SSE оставлен как deprecated-алиас). Состояние
сессии (конфиг, реестр сканеров, оркестратор, сторы,
in-memory реестр находок) живёт в одном объекте ``SessionState`` и
инициализируется лениво при первом обращении.

  scan_file, scan_diff, scan_project, get_fix_context, get_fix_context_batch,
  query_findings_db, export_snapshot, get_config, update_config,
  submit_feedback, get_scan_history, suppress_finding

Hook-хендлеры (session_start, pre_tool_use, post_tool_use) не являются
MCP-инструментами: они живут в hooks.py и вызываются через CLI
`appsecgate-mcp hook <name>`.

Постоянный ``FindingStore`` (показанные находки + контекст + идентичность)
держится в SQLite под ``project_id``-осью. ``submit_feedback`` /
``suppress_finding`` оперируют ``finding_id``, который
совпадает с ``fingerprint`` находки. Находки последних сканов держатся в
памяти процесса (``SessionState.findings``).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import uuid
import warnings
from collections import OrderedDict
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from appsecgate_mcp.config.loader import PROJECT_CONFIG_REL, ConfigLoader, deep_merge
from appsecgate_mcp.config.models import Config
from appsecgate_mcp.git import GitError, git_changed_files
from appsecgate_mcp.models.finding import Finding, ScanResult, Suppression
from appsecgate_mcp.orchestration.context_builder import ContextBuilder
from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.orchestration.gate import GateEngine, GateSummary
from appsecgate_mcp.rules import (
    TrivyDbStatus,
    seed_trivy_db,
    sync_trivy_db,
    trivy_db_status,
)
from appsecgate_mcp.scanners.registry import ScannerRegistry
from appsecgate_mcp.storage.db import Database, init_databases
from appsecgate_mcp.storage.query import ReadOnlyQueryError, init_views, run_query
from appsecgate_mcp.storage.stores import (
    FeedbackStore,
    FindingContextStore,
    FindingIdentityStore,
    ProjectsStore,
    ScanCacheStore,
    ShownFindingsStore,
    SqlAuditLogStore,
    SuppressionStore,
)

# Инструменты агента, означающие запись/правку файлов (для post_tool_use).
_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "write",
        "edit",
        "multiedit",
        "notebookedit",
        "create_file",
        "str_replace_editor",
        "apply_patch",
    }
)

# Максимум находок, удерживаемых в памяти (защита от неограниченного роста).
_MAX_IN_MEMORY_FINDINGS = 2000


def _resolve_default_project() -> str:
    """Определяет корень проекта: env → /workspace (docker) → cwd."""
    for env_key in ("APPSECGATE_PROJECT_PATH", "APPSECGATE_WORKSPACE"):
        value = os.environ.get(env_key)
        if value:
            return str(Path(value).resolve())
    if Path("/workspace").is_dir():
        return "/workspace"
    return str(Path.cwd().resolve())


def _compute_project_id(project_path: str) -> str:
    """Стабильная проектная идентичность: ``sha256(realpath(project_path))[:16]``.

    Проект определяется физическим путём (симлинки раскрываются через
    ``resolve()``), поэтому два разных представления одного и того же каталога
    дают одинаковый ``project_id`` (arch §4.10).
    """
    return hashlib.sha256(str(Path(project_path).resolve()).encode()).hexdigest()[:16]


def _resolve_inside_project(path: str, project: str) -> Path:
    """Разрешает путь и проверяет, что он лежит внутри корня проекта.

    Относительные пути считаются от корня проекта. Симлинки раскрываются через
    resolve(), поэтому ссылка, ведущая наружу, отклоняется. Для пустого пути и
    пути вне проекта поднимается ValueError.
    """
    if not path or not path.strip():
        raise ValueError("path is empty")
    base = Path(project).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"path outside project: {path}")
    return resolved


class SessionState:
    """Состояние одной сессии MCP-сервера (живёт в памяти процесса)."""

    def __init__(self) -> None:
        self.initialized = False
        # Идентификатор сессии для sql_audit_log (arch §8.4 п. 3.2).
        self.session_id: str = uuid.uuid4().hex
        self.project_path = _resolve_default_project()
        self.project_id: str | None = None
        self.project_alias: str | None = None
        self.config: Config | None = None
        self.registry: ScannerRegistry | None = None
        self.coordinator: ScanCoordinator | None = None
        self.context_builder: ContextBuilder | None = None
        self.gate_engine: GateEngine | None = None

        self.databases: dict[str, Database] = {}
        self.shown_store: ShownFindingsStore | None = None
        self.feedback_store: FeedbackStore | None = None
        self.suppression_store: SuppressionStore | None = None
        self.scan_cache_store: ScanCacheStore | None = None
        self.projects_store: ProjectsStore | None = None
        self.finding_identity_store: FindingIdentityStore | None = None
        self.finding_context_store: FindingContextStore | None = None
        self.sql_audit_store: SqlAuditLogStore | None = None

        self.findings: OrderedDict[str, Finding] = OrderedDict()
        self.config_loader = ConfigLoader()
        self.trivy_db: TrivyDbStatus | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Инициализация / завершение
    # ------------------------------------------------------------------
    async def initialize(self, project_path: str | None = None, *, force: bool = False) -> None:
        """(Пере)собирает сессию под блокировкой. Повторный вызов без force — no-op."""
        async with self._lock:
            if self.initialized and not force:
                return
            await self._initialize_locked(project_path, force=force)

    async def _initialize_locked(self, project_path: str | None, *, force: bool) -> None:
        """Тело инициализации. Вызывать только при удержании self._lock."""
        if force:
            await self.close()

        project = str(Path(project_path).resolve()) if project_path else self.project_path
        project_id = _compute_project_id(project)

        if self.project_id is not None and self.project_id != project_id:
            raise ValueError(
                f"project_path изменился в рамках сессии: "
                f"зафиксирован {self.project_id}, получен {project_id}"
            )
        self.project_id = project_id
        self.project_alias = Path(project).name
        self.project_path = project

        config = self.config_loader.load(project)
        self.config = config

        await self._sync_trivy_db(config)

        self.registry = ScannerRegistry.from_config(config, project_path=project)

        await self._init_storage(config)

        self.coordinator = ScanCoordinator(
            config,
            self.registry,
            suppression_store=self.suppression_store,
            shown_store=self.shown_store,
            identity_store=self.finding_identity_store,
            context_store=self.finding_context_store,
            project_root=project,
            project_id=project_id,
        )
        self.context_builder = ContextBuilder(
            self.finding_context_store,
            project_root=project,
            project_id=project_id,
            project_alias=self.project_alias,
            feedback_store=self.feedback_store,
        )
        self.gate_engine = GateEngine(config, shown_store=self.shown_store)
        self.initialized = True

    async def _init_storage(self, config: Config) -> None:
        """Создаёт три SQLite-базы и инициализирует их схемы."""
        base = Path(config.data_dir) if config.data_dir else Path.home() / ".appsecgate-mcp"
        paths = {
            "shown": base / "shown_findings.db",
            "feedback": base / "feedback.db",
            "scan_cache": base / "scan_cache.db",
        }
        self.databases = await init_databases(paths)

        project_id = self.project_id
        assert project_id is not None  # фиксируется в initialize() до _init_storage
        self.shown_store = ShownFindingsStore(self.databases["shown"], project_id)
        self.shown_store.init_schema()
        self.feedback_store = FeedbackStore(self.databases["feedback"])
        self.feedback_store.init_schema()
        self.suppression_store = SuppressionStore(self.databases["shown"])
        self.suppression_store.init_schema()
        self.scan_cache_store = ScanCacheStore(self.databases["scan_cache"])
        self.scan_cache_store.init_schema()

        self.projects_store = ProjectsStore(self.databases["shown"])
        self.projects_store.init_schema()
        self.finding_identity_store = FindingIdentityStore(self.databases["shown"])
        self.finding_identity_store.init_schema()
        self.finding_context_store = FindingContextStore(self.databases["shown"])
        self.finding_context_store.init_schema()
        self.sql_audit_store = SqlAuditLogStore(self.databases["shown"])
        self.sql_audit_store.init_schema()

        # Публичные views для query_findings_db (arch §4.4, §4.7).
        init_views(self.databases["shown"])

        await self.projects_store.upsert(project_id, self.project_alias or "", self.project_path)

    async def _sync_trivy_db(self, config: Config) -> None:
        """Seed + (опц.) онлайн-синхронизация Trivy DB, затем статус (дизайн v1 §2.3).

        Один раз на `session_start`, не на каждый скан. Онлайн-синхронизация
        только при `network.mode: online` и `network.sync.trivy_db`, с таймаутом
        и fallback на локальную БД (fail-soft). Ошибки не роняют инициализацию.
        """
        cache_dir = os.environ.get("TRIVY_CACHE_DIR")
        try:
            seed_trivy_db(cache_dir=cache_dir)
        except OSError:
            pass

        if config.network.is_online() and config.network.sync.trivy_db:
            warning = await sync_trivy_db(
                cache_dir=cache_dir,
                timeout_seconds=config.network.sync.timeout_seconds,
            )
            if warning and warning not in config.rules_warnings:
                config.rules_warnings.append(warning)

        self.trivy_db = trivy_db_status(
            cache_dir=cache_dir,
            max_age_days=config.network.sync.max_db_age_days,
        )

    async def close(self) -> None:
        for db in self.databases.values():
            try:
                db.close()
            except Exception:
                pass
        self.databases = {}
        self.initialized = False

    # ------------------------------------------------------------------
    # In-memory реестр находок
    # ------------------------------------------------------------------
    def register(self, result: ScanResult) -> None:
        """Регистрирует находки; при переполнении вытесняются самые старые."""
        for finding in result.findings:
            self.findings[finding.fingerprint] = finding
            self.findings.move_to_end(finding.fingerprint)
        while len(self.findings) > _MAX_IN_MEMORY_FINDINGS:
            self.findings.popitem(last=False)

    def get_finding(self, finding_id: str) -> Finding | None:
        return self.findings.get(finding_id)


async def _ensure_session(project_path: str | None = None) -> SessionState:
    """Лениво инициализирует сессию при первом обращении."""
    await _session.initialize(project_path)
    return _session


async def _build_scan_output(state: SessionState, result: ScanResult) -> dict[str, Any]:
    """Собирает сериализуемый ответ: сводка + findings + gate-решения + meta."""
    gate: GateSummary | None = None
    if state.gate_engine is not None:
        gate = await state.gate_engine.evaluate_all(result.findings, mode="local")
    # Хэш набора правил фиксируем в meta каждого скана (дизайн v1 §1.5).
    if state.config is not None and state.config.resolved_rules is not None:
        result.meta.ruleset_hash = state.config.resolved_rules.ruleset_hash
    meta = result.meta.model_dump(mode="json")
    # Trivy DB-предупреждения живут в meta.warnings (дизайн v1 §2.3, §4.4).
    if state.trivy_db is not None:
        for warning in state.trivy_db.collect_warnings():
            if warning not in meta["warnings"]:
                meta["warnings"].append(warning)
    payload: dict[str, Any] = {
        "summary": result.to_summary(),
        "findings": [f.model_dump(mode="json") for f in result.findings],
        "meta": meta,
    }
    if gate is not None:
        payload["gate"] = {
            "mode": gate.mode,
            "blocked": gate.block_count,
            "warned": len(gate.warned),
            "informed": len(gate.informed),
            "should_fail": gate.should_fail,
        }
    return payload


# ----------------------------------------------------------------------
# FastMCP instance
# ----------------------------------------------------------------------
mcp = FastMCP("appsecgate-mcp")
_session = SessionState()


# ----------------------------------------------------------------------
# MCP tools
# ----------------------------------------------------------------------
@mcp.tool()
async def scan_file(path: str) -> dict[str, Any]:
    """Сканирует один файл и возвращает нормализованные находки.

    path — путь к файлу (абсолютный или относительный от корня проекта).
    """
    state = await _ensure_session()
    try:
        resolved = _resolve_inside_project(path, state.project_path)
    except ValueError as exc:
        return {"error": str(exc), "findings": [], "summary": {"total": 0}}
    if not resolved.is_file():
        return {"error": f"file not found: {path}", "findings": [], "summary": {"total": 0}}
    rel = str(resolved.relative_to(Path(state.project_path).resolve()))
    result = await state.coordinator.scan([rel], mode="file")
    state.register(result)
    return await _build_scan_output(state, result)


@mcp.tool()
async def scan_diff() -> dict[str, Any]:
    """Сканирует staged + unstaged + untracked изменения текущего git-репозитория."""
    state = await _ensure_session()
    try:
        files = await git_changed_files(state.project_path)
    except GitError as exc:
        return {"error": f"git error: {exc}", "findings": [], "summary": {"total": 0}}
    if not files:
        empty = ScanResult()
        empty.meta.mode = "diff"
        empty.meta.scanned_files = []
        return await _build_scan_output(state, empty)
    result = await state.coordinator.scan(files, mode="diff")
    state.register(result)
    return await _build_scan_output(state, result)


@mcp.tool()
async def scan_project(path: str = ".") -> dict[str, Any]:
    """Сканирует весь проект или конкретную директорию внутри него.

    path — директория (абсолютная или относительная от корня проекта).
    По умолчанию сканируется весь проект. Запускаются все сканеры в режиме
    `project`: semgrep — по файлам, gitleaks/trufflehog/trivy — по директории.
    """
    state = await _ensure_session()
    try:
        target = _resolve_inside_project(path or ".", state.project_path)
    except ValueError as exc:
        return {"error": str(exc), "findings": [], "summary": {"total": 0}}
    if not target.exists():
        return {"error": f"path not found: {path}", "findings": [], "summary": {"total": 0}}
    if not target.is_dir():
        return {
            "error": f"not a directory: {path} (используйте scan_file для файла)",
            "findings": [],
            "summary": {"total": 0},
        }

    rel = str(target.relative_to(Path(state.project_path).resolve()))
    # announce-only: сканируем без записи в shown/identity/context (§4.3, F3).
    result = await state.coordinator.scan([rel], mode="project", persist=False)
    return await _build_announce_output(state, result)


def _by_file_top10(findings: list[Finding]) -> list[dict[str, Any]]:
    """Топ-10 файлов по числу находок (для announce-сводки scan_project)."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.file_path] = counts.get(f.file_path, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"file_path": fp, "count": n} for fp, n in ranked[:10]]


async def _build_announce_output(state: SessionState, result: ScanResult) -> dict[str, Any]:
    """Собирает announce-формат scan_project (arch §4.3)."""
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for f in result.findings:
        sev = f.severity.value
        by_severity[sev] = by_severity.get(sev, 0) + 1
        cat = f.category.value
        by_category[cat] = by_category.get(cat, 0) + 1

    ranked = sorted(result.findings, key=lambda f: f.sort_key(), reverse=True)
    top = ranked[:20]
    top_findings = [
        {
            "finding_id": f.fingerprint,
            "logical_id": None,
            "rule_id": f.rule_id,
            "file_path": f.file_path,
            "severity": f.severity.value,
            "scanner": f.scanner,
            "line_start": f.line_start,
        }
        for f in top
    ]

    return {
        "project": {
            "project_id": state.project_id,
            "project_alias": state.project_alias,
        },
        "summary": {
            "total": result.total,
            "by_severity": by_severity,
            "by_category": by_category,
            "by_file_top10": _by_file_top10(result.findings),
        },
        "top_findings": top_findings,
        "next_actions": [
            "query_findings_db(\"SELECT logical_id, severity FROM v_findings WHERE severity = 'high' LIMIT 50\")",
            "get_fix_context(finding_id='<finding_id>')",
            "get_fix_context_batch(finding_ids=['<id1>', '<id2>'])",
        ],
        "truncated": result.total > len(top_findings),
        "total_available": result.total,
    }


@mcp.tool()
async def get_config() -> dict[str, Any]:
    """Возвращает действующую (merged) конфигурацию сессии."""
    state = await _ensure_session()
    return state.config.model_dump(mode="json")


# Шов для тестов: подменяется точечно, не трогая os.replace глобально.
_replace_file = os.replace


def _atomic_write(path: Path, text: str) -> None:
    """Атомарная запись: временный файл в той же директории, затем _replace_file (os.replace)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        _replace_file(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _format_validation_errors(exc: ValidationError) -> list[str]:
    """Превращает ошибки pydantic в строки вида 'путь.к.полю: сообщение'."""
    messages: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        messages.append(f"{loc}: {err['msg']}")
    return messages


def _restore_config(path: Path, previous_text: str | None) -> None:
    """Возвращает файл конфига к предыдущему содержимому (или удаляет, если его не было)."""
    if previous_text is None:
        path.unlink(missing_ok=True)
    else:
        _atomic_write(path, previous_text)


async def _reinitialize(state: SessionState) -> None:
    """Пересоздаёт ConfigLoader и переинициализирует сессию под текущий проект."""
    state.config_loader = ConfigLoader(state.config_loader.default_config_path)
    await state.initialize(state.project_path, force=True)


@mcp.tool()
async def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    """Глубоко мёржит updates в .appsecgate-mcp/config.yaml проекта и перезагружает сессию.

    Итоговый конфиг проверяется той же схемой, что и ConfigLoader.load, до записи.
    Невалидный результат возвращается как status=invalid, файл не меняется.
    """
    state = await _ensure_session()
    project_conf = Path(state.project_path) / PROJECT_CONFIG_REL

    existing: dict[str, Any] = {}
    previous_text: str | None = None
    if project_conf.exists():
        previous_text = project_conf.read_text(encoding="utf-8")
        try:
            existing = yaml.safe_load(previous_text) or {}
        except yaml.YAMLError:
            existing = {}
    merged = deep_merge(existing, updates)

    try:
        Config.model_validate(state.config_loader.validation_layers(merged))
    except ValidationError as exc:
        return {"status": "invalid", "errors": _format_validation_errors(exc)}

    project_conf.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(project_conf, yaml.safe_dump(merged, allow_unicode=True, sort_keys=False))

    try:
        await _reinitialize(state)
    except Exception as exc:
        _restore_config(project_conf, previous_text)
        try:
            await _reinitialize(state)
        except Exception:
            pass
        return {
            "status": "error",
            "reason": f"reinitialization failed, config rolled back: {exc}",
            "config_path": str(project_conf),
        }
    return {
        "status": "updated",
        "config_path": str(project_conf),
        "config": state.config.model_dump(mode="json"),
    }


@mcp.tool()
async def submit_feedback(finding_id: str, type: str, reason: str = "") -> dict[str, Any]:
    """Отправляет обратную связь по находке.

    type: FALSE_POSITIVE | CONFIRMED | WONT_FIX.
    """
    state = await _ensure_session()
    try:
        feedback_id = await state.feedback_store.save(finding_id, type, reason)
    except ValueError as exc:
        return {"status": "error", "reason": str(exc)}
    return {"status": "recorded", "finding_id": finding_id, "feedback_id": feedback_id}


def _relative_project_path(path: str, project: str) -> str:
    """Приводит путь (абсолютный или относительный) к виду от корня проекта.

    Результат всегда с прямыми слэшами и без ведущего './'. Путь вне проекта
    поднимает ValueError (см. _resolve_inside_project).
    """
    resolved = _resolve_inside_project(path, project)
    return resolved.relative_to(Path(project).resolve()).as_posix()


def _normalize_history_item(item: dict[str, Any], project: str) -> dict[str, Any] | None:
    """Приводит file_path строки журнала к виду от корня проекта.

    Возвращает None, если путь лежит вне проекта: такая строка не попадает в ответ.
    """
    raw = item.get("file_path")
    if not isinstance(raw, str) or not raw:
        return item
    try:
        rel = _relative_project_path(raw, project)
    except ValueError:
        return None
    return {**item, "file_path": rel}


@mcp.tool()
async def get_scan_history(limit: int = 50, file_path: str | None = None) -> dict[str, Any]:
    """Возвращает журнал показанных находок (shown_findings.db).

    Пути в items всегда относительные от корня проекта. Строки с путями вне
    проекта исключаются из ответа.
    """
    state = await _ensure_session()
    try:
        if file_path:
            rel = _relative_project_path(file_path, state.project_path)
            rows = await state.shown_store.get_by_file(rel)
        else:
            rows = await state.shown_store.get_all(limit)
    except Exception as exc:
        return {"status": "error", "reason": str(exc), "items": []}
    items = [
        n for row in rows if (n := _normalize_history_item(row, state.project_path)) is not None
    ]
    items = items[:limit]
    return {"count": len(items), "items": items}


@mcp.tool()
async def suppress_finding(
    finding_id: str, reason: str, expires_at: str | None = None
) -> dict[str, Any]:
    """Создаёт локальный suppression (не влияет на CI-контур в Фазе 1)."""
    state = await _ensure_session()
    suppression = Suppression(
        fingerprint=finding_id,
        reason=reason,
        scope="local",
        expires_at=expires_at,
    )
    await state.suppression_store.create(suppression)
    try:
        await state.shown_store.mark_suppressed(finding_id, reason)
    except Exception:
        pass
    return {"status": "suppressed", "finding_id": finding_id}


@mcp.tool()
async def get_fix_context(finding_id: str) -> dict[str, Any]:
    """Возвращает ContextPack находки (finding + окно кода + rule doc)."""
    state = await _ensure_session()
    if state.context_builder is None:
        return {"status": "error", "reason": "session not initialized"}
    pack = await state.context_builder.build(finding_id)
    if pack is None:
        return {
            "status": "error",
            "reason": f"finding not found or not eligible for context: {finding_id}",
        }
    return {"status": "ok", "context": pack.model_dump(mode="json")}


_BATCH_LIMIT = 20


@mcp.tool()
async def get_fix_context_batch(finding_ids: list[str]) -> dict[str, Any]:
    """Возвращает ContextPack для набора находок (лимит 20)."""
    state = await _ensure_session()
    if len(finding_ids) > _BATCH_LIMIT:
        return {
            "status": "error",
            "reason": f"batch limit exceeded: max {_BATCH_LIMIT} findings",
            "limit": _BATCH_LIMIT,
        }
    if state.context_builder is None:
        return {"status": "error", "reason": "session not initialized"}
    contexts: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for finding_id in finding_ids:
        pack = await state.context_builder.build(finding_id)
        if pack is None:
            errors[finding_id] = "not found or not eligible for context"
        else:
            contexts.append(pack.model_dump(mode="json"))
    return {"status": "ok", "contexts": contexts, "errors": errors, "count": len(contexts)}


@mcp.tool()
async def query_findings_db(sql: str, params: list[Any] | None = None) -> dict[str, Any]:
    """Выполняет read-only SELECT по публичным views (v_findings, v_summary, v_projects)."""
    state = await _ensure_session()
    if state.project_id is None or "shown" not in state.databases:
        return {"status": "error", "reason": "session not initialized"}
    db_path = state.databases["shown"].path
    try:
        result = await asyncio.to_thread(run_query, db_path, sql, params, state.project_id)
    except ReadOnlyQueryError as exc:
        return {"status": "error", "reason": str(exc)}
    except sqlite3.Error as exc:
        return {"status": "error", "reason": f"sql error: {exc}"}

    # Каждый запрос — в sql_audit_log (arch §4.4, требование F19).
    if state.sql_audit_store is not None:
        try:
            await state.sql_audit_store.record(
                state.project_id,
                state.session_id,
                result["sql"],
                int(result["duration_ms"]),
                result["row_count"],
            )
        except Exception:
            pass

    return {
        "status": "ok",
        "rows": result["rows"],
        "row_count": result["row_count"],
        "sql": result["sql"],
    }


@mcp.tool()
async def export_snapshot(
    path: str, format: str = "ndjson", project_id: str | None = None
) -> dict[str, Any]:
    """Экспортирует снапшот находок в ndjson (parquet — в Фазе 2)."""
    state = await _ensure_session()
    if format == "parquet":
        return {
            "status": "error",
            "reason": (
                "parquet export is not available in Phase 1 "
                "(no new production dependencies); use format='ndjson'"
            ),
        }
    if format != "ndjson":
        return {"status": "error", "reason": f"unsupported format: {format}"}
    if state.project_id is None or "shown" not in state.databases:
        return {"status": "error", "reason": "session not initialized"}

    pid = project_id or state.project_id
    db_path = state.databases["shown"].path
    try:
        result = await asyncio.to_thread(
            run_query, db_path, "SELECT * FROM v_findings LIMIT 100000", None, pid
        )
    except (ReadOnlyQueryError, sqlite3.Error) as exc:
        return {"status": "error", "reason": str(exc)}

    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"status": "error", "reason": f"cannot create directory: {exc}"}

    text = "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in result["rows"])
    if text:
        text += "\n"
    try:
        _atomic_write(target, text)
    except OSError as exc:
        return {"status": "error", "reason": f"cannot write snapshot: {exc}"}

    return {
        "status": "ok",
        "path": str(target),
        "format": "ndjson",
        "rows": result["row_count"],
    }


# ----------------------------------------------------------------------
# Entrypoint
# ----------------------------------------------------------------------
def _configure_http(host: str, port: int) -> None:
    """Задаёт host/port для HTTP-транспортов (best-effort по версиям MCP)."""
    try:
        mcp.settings.host = host
        mcp.settings.port = port
    except Exception:
        os.environ.setdefault("FASTMCP_HOST", host)
        os.environ.setdefault("FASTMCP_PORT", str(port))


def _build_parser() -> argparse.ArgumentParser:
    """Собирает CLI-парсер (вынесено отдельно для тестируемости)."""
    parser = argparse.ArgumentParser(prog="appsecgate-mcp", description="AppSecGate MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default=os.environ.get("APPSECGATE_TRANSPORT", "stdio"),
        help=(
            "stdio — основной (по умолчанию); streamable-http — HTTP-демон; "
            "sse — устаревший HTTP-транспорт (deprecated, используйте streamable-http)."
        ),
    )
    parser.add_argument("--host", default=os.environ.get("APPSECGATE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("APPSECGATE_PORT", "8765")))
    parser.add_argument(
        "--project",
        default=os.environ.get("APPSECGATE_PROJECT_PATH") or os.environ.get("APPSECGATE_WORKSPACE"),
        help="Корень проекта для сканирования",
    )
    return parser


def main() -> None:
    """Точка входа: appsecgate-mcp / python -m appsecgate_mcp.

    `appsecgate-mcp hook <name>` запускает хук (JSON из stdin, JSON в stdout).
    Без подкоманды поднимается MCP-сервер, как раньше.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "hook":
        from appsecgate_mcp.hooks import hook_main  # ленивый импорт: нет цикла с server

        raise SystemExit(hook_main(sys.argv[2:]))
    args = _build_parser().parse_args()

    if args.project:
        _session.project_path = str(Path(args.project).resolve())

    transport = args.transport
    if transport == "sse":
        warnings.warn(
            "Транспорт 'sse' устарел и заменён на 'streamable-http' "
            "(MCP spec 2025-03-26). Используйте --transport streamable-http.",
            DeprecationWarning,
            stacklevel=2,
        )
    if transport != "stdio":
        _configure_http(args.host, args.port)

    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
