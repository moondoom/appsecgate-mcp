"""SessionState — состояние одной сессии MCP-сервера и ленивая инициализация.

Тесты патчат ``server._session`` и ``server._ensure_session`` (test_session_lock,
test_update_config), поэтому и ``_session``, и зависящие от него точки
читаются с пакета ``appsecgate_mcp.server`` отложенно через ``_server_mod()``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from appsecgate_mcp.config.loader import ConfigLoader
from appsecgate_mcp.config.models import Config
from appsecgate_mcp.models.finding import Finding, ScanResult
from appsecgate_mcp.orchestration.context_builder import ContextBuilder
from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.orchestration.gate import GateEngine
from appsecgate_mcp.rules import TrivyDbStatus, seed_trivy_db, trivy_db_status
from appsecgate_mcp.scanners.registry import ScannerRegistry
from appsecgate_mcp.server.project_identity import (  # noqa: F401 (реэкспорт в фасад)
    _compute_project_id,
    _find_git_dir,
    _git_identity,
    _repo_name_from_git_url,
    _resolve_project_identity,
)
from appsecgate_mcp.storage.query import init_views
from appsecgate_mcp.storage.stores import (
    FeedbackStore,
    FindingContextStore,
    FindingIdentityStore,
    FixAttemptsStore,
    ProjectsStore,
    RemoteSuppressionStore,
    ScanCacheStore,
    ShownFindingsStore,
    SqlAuditLogStore,
    SuppressionStore,
)

logger = logging.getLogger(__name__)

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

# Retention: SHOWN без активности удаляется из shown_findings (arch §4.7).
_SHOWN_RETENTION_DAYS = 30


def _server_mod() -> Any:
    """Возвращает модуль ``appsecgate_mcp.server`` (пакет-фасад).

    Импорт выполняется на месте вызова, чтобы чтение атрибутов пакета всегда
    отражало текущее состояние (в том числе monkeypatch в тестах).
    """
    import appsecgate_mcp.server as server_mod

    return server_mod


def _retention_cutoff(days: int, *, now: datetime | None = None) -> str:
    """ISO-метка «момент минус days дней» — порог удаления для retention."""
    base = now or datetime.now(UTC)
    return (base - timedelta(days=days)).isoformat()


def _resolve_default_project() -> str:
    """Определяет корень проекта: env → /workspace (docker) → cwd."""
    for env_key in ("APPSECGATE_PROJECT_PATH", "APPSECGATE_WORKSPACE"):
        value = os.environ.get(env_key)
        if value:
            return str(Path(value).resolve())
    if Path("/workspace").is_dir():
        return "/workspace"
    return str(Path.cwd().resolve())


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
        # Явная идентичность из CLI/окружения (T9): если задана — перекрывает
        # git/путь при _resolve_project_identity. Приоритет: override > env.
        self.project_id_override: str | None = None
        self.project_alias_override: str | None = None
        self.config: Config | None = None
        self.registry: ScannerRegistry | None = None
        self.coordinator: ScanCoordinator | None = None
        self.context_builder: ContextBuilder | None = None
        self.gate_engine: GateEngine | None = None

        self.databases: dict[str, Any] = {}
        self.shown_store: ShownFindingsStore | None = None
        self.feedback_store: FeedbackStore | None = None
        self.suppression_store: SuppressionStore | None = None
        self.remote_suppression_store: RemoteSuppressionStore | None = None
        self.scan_cache_store: ScanCacheStore | None = None
        self.projects_store: ProjectsStore | None = None
        self.finding_identity_store: FindingIdentityStore | None = None
        self.finding_context_store: FindingContextStore | None = None
        self.fix_attempts_store: FixAttemptsStore | None = None
        self.sql_audit_store: SqlAuditLogStore | None = None

        self.findings: OrderedDict[str, Finding] = OrderedDict()
        self.last_results: dict[str, ScanResult] = {}
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
        explicit_id = (
            self.project_id_override or os.environ.get("APPSECGATE_PROJECT_ID") or ""
        ).strip() or None
        explicit_alias = (
            self.project_alias_override or os.environ.get("APPSECGATE_PROJECT_ALIAS") or ""
        ).strip() or None
        project_id, project_alias = _resolve_project_identity(
            project, explicit_id=explicit_id, explicit_alias=explicit_alias
        )
        logger.info("session init project_id=%s alias=%s", project_id, project_alias)

        if self.project_id is not None and self.project_id != project_id:
            raise ValueError(
                f"project_path изменился в рамках сессии: "
                f"зафиксирован {self.project_id}, получен {project_id}"
            )
        self.project_id = project_id
        self.project_alias = project_alias
        self.project_path = project

        config = self.config_loader.load(project, project_id=project_id)
        self.config = config

        await self._sync_trivy_db(config)

        self.registry = ScannerRegistry.from_config(
            config,
            project_path=project,
            timeout=float(os.environ.get("APPSECGATE_SCANNER_TIMEOUT", "120")),
        )
        logger.info(
            "session init scanners=%s categories=%s",
            self.registry.names(),
            config.enabled_scanner_categories(),
        )

        await self._init_storage(config)

        self.coordinator = ScanCoordinator(
            config,
            self.registry,
            suppression_store=self.suppression_store,
            remote_suppression_store=self.remote_suppression_store,
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
        self.databases = await _server_mod().init_databases(paths)

        project_id = self.project_id
        assert project_id is not None  # фиксируется в initialize() до _init_storage
        self.shown_store = ShownFindingsStore(self.databases["shown"], project_id)
        self.shown_store.init_schema()
        self.feedback_store = FeedbackStore(self.databases["feedback"])
        self.feedback_store.init_schema()
        self.suppression_store = SuppressionStore(self.databases["shown"], project_id)
        self.suppression_store.init_schema()
        self.remote_suppression_store = RemoteSuppressionStore(self.databases["shown"], project_id)
        self.remote_suppression_store.init_schema()
        self.scan_cache_store = ScanCacheStore(self.databases["scan_cache"])
        self.scan_cache_store.init_schema()

        self.projects_store = ProjectsStore(self.databases["shown"])
        self.projects_store.init_schema()
        self.finding_identity_store = FindingIdentityStore(self.databases["shown"])
        self.finding_identity_store.init_schema()
        self.finding_context_store = FindingContextStore(self.databases["shown"])
        self.finding_context_store.init_schema()
        self.fix_attempts_store = FixAttemptsStore(self.databases["shown"])
        self.fix_attempts_store.init_schema()
        self.sql_audit_store = SqlAuditLogStore(self.databases["shown"])
        self.sql_audit_store.init_schema()

        # Публичные views для query_findings_db (arch §4.4, §4.7).
        init_views(self.databases["shown"])

        await self.projects_store.upsert(project_id, self.project_alias or "", self.project_path)

        # Retention: удаляем SHOWN-находки без активности ≥ 30 дней (arch §4.7).
        await self.apply_retention()

    async def apply_retention(self) -> dict[str, int]:
        """Применяет retention policy к shown_findings (остальное — Фаза 2)."""
        removed = 0
        if self.shown_store is not None:
            try:
                removed = await self.shown_store.purge_stale_shown(
                    cutoff=_retention_cutoff(_SHOWN_RETENTION_DAYS)
                )
            except Exception:
                removed = 0
        return {"purged_shown": removed}

    async def _sync_trivy_db(self, config: Config) -> None:
        """Seed + (опц.) онлайн-синхронизация Trivy DB, затем статус.

        Один раз на `session_start`, не на каждый скан. Онлайн-синхронизация
        только при `network.mode: online` и `network.sync.trivy_db`, с таймаутом
        и fallback на локальную БД (fail-soft). Ошибки не роняют инициализацию.
        """
        cache_dir = os.environ.get("TRIVY_CACHE_DIR")
        try:
            seeded = seed_trivy_db(cache_dir=cache_dir)
            logger.info("trivy db seed done seeded=%s", seeded)
        except OSError:
            pass

        if config.network.is_online() and config.network.sync.trivy_db:
            logger.info("trivy db sync online timeout=%s", config.network.sync.timeout_seconds)
            warning = await _server_mod().sync_trivy_db(
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
        self.last_results = {}
        self.initialized = False

    # ------------------------------------------------------------------
    # In-memory реестр находок
    # ------------------------------------------------------------------
    def register(self, result: ScanResult) -> None:
        """Регистрирует находки; при переполнении вытесняются самые старые."""
        scope = "full" if result.meta.mode == "project" else result.meta.mode
        if scope in ("file", "diff", "full"):
            self.last_results[scope] = result
        for finding in result.findings:
            self.findings[finding.fingerprint] = finding
            self.findings.move_to_end(finding.fingerprint)
        while len(self.findings) > _MAX_IN_MEMORY_FINDINGS:
            self.findings.popitem(last=False)

    def get_finding(self, finding_id: str) -> Finding | None:
        return self.findings.get(finding_id)


_session = SessionState()


async def _ensure_session(project_path: str | None = None) -> SessionState:
    """Лениво инициализирует сессию при первом обращении.

    ``_session`` читается с пакета отложенно: тесты патчат ``server._session``
    (test_session_lock, test_update_config).
    """
    await _server_mod()._session.initialize(project_path)
    return _server_mod()._session
