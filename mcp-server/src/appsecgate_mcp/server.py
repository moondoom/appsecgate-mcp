"""MCP Server Layer — FastMCP-сервер AppSecGate (Фаза 1).


Регистрирует 9 MCP-инструментов, обслуживает stdio и
streamable-http транспорты (SSE оставлен как deprecated-алиас). Состояние
сессии (конфиг, реестр сканеров, оркестратор, сторы,
in-memory реестр находок) живёт в одном объекте ``SessionState`` и
инициализируется лениво при первом обращении.

  scan_file, scan_diff, scan_project, auto_fix, get_config, update_config,
  submit_feedback, get_scan_history, suppress_finding

Hook-хендлеры (session_start, pre_tool_use, post_tool_use) не являются
MCP-инструментами: они живут в hooks.py и вызываются через CLI
`appsecgate-mcp hook <name>`.

Поскольку постоянного ``FindingStore`` в Фазе 1 нет, ``auto_fix`` /
``submit_feedback`` / ``suppress_finding`` оперируют ``finding_id``, который
совпадает с ``fingerprint`` находки. Находки последних сканов держатся в
памяти процесса (``SessionState.findings``).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
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
from appsecgate_mcp.orchestration.autofixer import AutoFixer
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
from appsecgate_mcp.storage.stores import (
    FeedbackStore,
    ScanCacheStore,
    ShownFindingsStore,
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
        self.project_path = _resolve_default_project()
        self.config: Config | None = None
        self.registry: ScannerRegistry | None = None
        self.coordinator: ScanCoordinator | None = None
        self.gate_engine: GateEngine | None = None
        self.auto_fixer: AutoFixer | None = None

        self.databases: dict[str, Database] = {}
        self.shown_store: ShownFindingsStore | None = None
        self.feedback_store: FeedbackStore | None = None
        self.suppression_store: SuppressionStore | None = None
        self.scan_cache_store: ScanCacheStore | None = None

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
            project_root=project,
        )
        self.gate_engine = GateEngine(config, shown_store=self.shown_store)
        self.auto_fixer = AutoFixer(config)
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

        self.shown_store = ShownFindingsStore(self.databases["shown"])
        self.shown_store.init_schema()
        self.feedback_store = FeedbackStore(self.databases["feedback"])
        self.feedback_store.init_schema()
        self.suppression_store = SuppressionStore(self.databases["shown"])
        self.suppression_store.init_schema()
        self.scan_cache_store = ScanCacheStore(self.databases["scan_cache"])
        self.scan_cache_store.init_schema()

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
    result = await state.coordinator.scan([rel], mode="project")
    state.register(result)
    return await _build_scan_output(state, result)


@mcp.tool()
async def auto_fix(finding_id: str, strategy: str = "patch") -> dict[str, Any]:
    """Пытается автоматически исправить находку по её finding_id (fingerprint).

    strategy: "patch" (готовый патч из метаданных) | "suggestion" (заглушка Фазы 1).
    """
    state = await _ensure_session()
    finding = state.get_finding(finding_id)
    if finding is None:
        return {
            "status": "failed",
            "finding_id": finding_id,
            "reason": "unknown finding_id — выполните scan_file/scan_diff сначала",
        }
    result = await state.auto_fixer.fix(finding, strategy)
    if result.status == "patched" and state.shown_store is not None:
        try:
            await state.shown_store.mark_fixed(finding_id)
        except Exception:
            pass
    return result.model_dump(mode="json")


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
