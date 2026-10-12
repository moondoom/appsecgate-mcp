"""Smoke-тесты MCP Server Layer: регистрация инструментов, хуков и CLI."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from appsecgate_mcp import server
from appsecgate_mcp.config.models import Config
from appsecgate_mcp.models.finding import ScanResult
from appsecgate_mcp.rules import trivy_db


def test_all_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    expected = {
        "scan_file",
        "scan_diff",
        "scan_project",
        "auto_fix",
        "get_config",
        "update_config",
        "submit_feedback",
        "get_scan_history",
        "suppress_finding",
        "session_start",
        "pre_tool_use",
        "post_tool_use",
    }
    assert expected.issubset(names)


def test_extract_touched_files(tmp_path, monkeypatch):
    monkeypatch.setattr(server._session, "project_path", str(tmp_path))
    files = server._extract_touched_files("Edit", {"file_path": "a.py"})
    assert files == ["a.py"]
    assert server._extract_touched_files("Read", {"file_path": "a.py"}) == []
    assert server._extract_touched_files("Write", {}) == []


def test_parser_accepts_streamable_http():
    parser = server._build_parser()
    args = parser.parse_args(["--transport", "streamable-http", "--port", "9000"])
    assert args.transport == "streamable-http"
    assert args.port == 9000


def test_parser_default_transport_is_stdio():
    parser = server._build_parser()
    assert parser.parse_args([]).transport == "stdio"


def test_parser_rejects_unknown_transport():
    parser = server._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--transport", "websocket"])


def test_sse_transport_emits_deprecation_warning(monkeypatch):
    # Не поднимаем реальный сервер — перехватываем mcp.run.
    captured: dict[str, str] = {}

    def fake_run(*, transport: str) -> None:
        captured["transport"] = transport

    monkeypatch.setattr(server.mcp, "run", fake_run)
    monkeypatch.setattr(server, "_configure_http", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", ["appsecgate-mcp", "--transport", "sse"])

    with pytest.warns(DeprecationWarning):
        server.main()
    assert captured["transport"] == "sse"


def test_streamable_http_configures_host_port(monkeypatch):
    captured: dict[str, str] = {}

    def fake_run(*, transport: str) -> None:
        captured["transport"] = transport

    configured: dict[str, int | str] = {}

    def fake_configure(host: str, port: int) -> None:
        configured["host"] = host
        configured["port"] = port

    monkeypatch.setattr(server.mcp, "run", fake_run)
    monkeypatch.setattr(server, "_configure_http", fake_configure)
    monkeypatch.setattr(
        "sys.argv",
        ["appsecgate-mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8123"],
    )

    server.main()
    assert captured["transport"] == "streamable-http"
    assert configured == {"host": "0.0.0.0", "port": 8123}


# ----------------------------------------------------------------------
# Этап 4: Trivy DB seed + возраст + network.mode (session-level)
# ----------------------------------------------------------------------
def _write_trivy_cache(
    cache: Path,
    *,
    updated_at: datetime | None,
    java_db: bool = False,
) -> Path:
    """Готовит фейковый кэш Trivy DB (metadata.json + trivy.db)."""
    db_dir = cache / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / "trivy.db").write_bytes(b"sqlite")
    payload: dict[str, object] = {}
    if updated_at is not None:
        payload["UpdatedAt"] = updated_at.isoformat()
    (db_dir / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    if java_db:
        java_dir = cache / "java-db"
        java_dir.mkdir(parents=True, exist_ok=True)
        (java_dir / "metadata.json").write_text("{}", encoding="utf-8")
    return cache


async def test_sync_trivy_db_offline_skips_network(tmp_path, monkeypatch):
    """Офлайн-режим: сетевой синк не вызывается, статус всё равно считается."""
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(tmp_path / "trivy"))
    calls = {"n": 0}

    async def fake_sync(**kwargs):  # pragma: no cover - не должен вызываться
        calls["n"] += 1
        return None

    monkeypatch.setattr(server, "sync_trivy_db", fake_sync)
    state = server.SessionState()
    await state._sync_trivy_db(Config())

    assert calls["n"] == 0
    assert state.trivy_db is not None
    assert state.trivy_db.present is False  # кэш пуст → warning


async def test_sync_trivy_db_online_calls_sync_with_timeout(tmp_path, monkeypatch):
    """Онлайн-режим: синк вызывается один раз с таймаутом из конфига."""
    cache = tmp_path / "trivy"
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(cache))
    captured: dict[str, object] = {}

    async def fake_sync(*, cache_dir=None, timeout_seconds=30):
        captured["cache_dir"] = cache_dir
        captured["timeout"] = timeout_seconds
        return None

    monkeypatch.setattr(server, "sync_trivy_db", fake_sync)
    config = Config()
    config.network.mode = "online"
    config.network.sync.timeout_seconds = 7

    state = server.SessionState()
    await state._sync_trivy_db(config)

    assert captured == {"cache_dir": str(cache), "timeout": 7}
    assert state.trivy_db is not None


async def test_sync_trivy_db_online_sync_failure_is_soft(tmp_path, monkeypatch):
    """Ошибка синка не роняет инициализацию: warning + локальный статус."""
    cache = _write_trivy_cache(tmp_path / "trivy", updated_at=datetime.now(UTC))
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(cache))

    async def fake_sync(*, cache_dir=None, timeout_seconds=30):
        return "trivy db sync failed: timeout"

    monkeypatch.setattr(server, "sync_trivy_db", fake_sync)
    config = Config()
    config.network.mode = "online"

    state = server.SessionState()
    await state._sync_trivy_db(config)

    assert state.trivy_db is not None
    assert state.trivy_db.present is True  # локальная БД осталась доступна
    assert any("sync failed" in w for w in config.rules_warnings)


async def test_sync_trivy_db_seeds_from_seed_dir(tmp_path, monkeypatch):
    """Пустой кэш → seed-on-first-run копирует БД из seed-директории."""
    cache = tmp_path / "trivy"
    seed = tmp_path / "seed"
    _write_trivy_cache(seed, updated_at=datetime.now(UTC) - timedelta(days=2))
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(cache))
    monkeypatch.setattr(trivy_db, "DEFAULT_TRIVY_DB_SEED", str(seed))

    state = server.SessionState()
    await state._sync_trivy_db(Config())

    assert (cache / "db" / "trivy.db").exists()
    assert state.trivy_db is not None
    assert state.trivy_db.present is True
    assert state.trivy_db.age_days == 2


async def test_scan_output_includes_missing_db_warning(tmp_path):
    """Отсутствующая Trivy DB → warning попадает в meta.warnings, скан не падает."""
    state = server.SessionState()
    state.trivy_db = trivy_db.trivy_db_status(cache_dir=tmp_path / "missing", max_age_days=30)

    output = await server._build_scan_output(state, ScanResult())

    warnings = output["meta"]["warnings"]
    assert any("Trivy DB not found" in w for w in warnings)
    assert any("trivy_java_db_missing" in w for w in warnings)


async def test_scan_output_includes_stale_db_warning(tmp_path):
    """Устаревшая Trivy DB → warning с версией/возрастом/порогом."""
    now = datetime.now(UTC)
    cache = _write_trivy_cache(tmp_path / "trivy", updated_at=now - timedelta(days=47))
    state = server.SessionState()
    state.trivy_db = trivy_db.trivy_db_status(cache_dir=cache, max_age_days=30)

    output = await server._build_scan_output(state, ScanResult())

    warnings = output["meta"]["warnings"]
    assert any("age: 47 days" in w and "threshold: 30" in w for w in warnings)


async def test_session_start_reports_trivy_db(tmp_path, monkeypatch):
    """`session_start` отдаёт `trivy_db` со статусом и warnings (дизайн v1 §4.4)."""
    cache = _write_trivy_cache(tmp_path / "trivy", updated_at=datetime.now(UTC) - timedelta(days=9))
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(cache))
    monkeypatch.setenv("APPSECGATE_MCP_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(server, "_session", server.SessionState())

    out = await server.session_start(str(tmp_path))

    assert out["status"] == "ready"
    trivy = out["trivy_db"]
    assert trivy is not None
    assert trivy["present"] is True
    assert trivy["age_days"] == 9
    # Java DB нет → соответствующий warning присутствует.
    assert trivy["java_warning"] is not None


# ----------------------------------------------------------------------
# Этап 5: meta правил и ruleset_hash (дизайн v1 §1.5, §4.4)
# ----------------------------------------------------------------------
async def test_session_start_reports_rules_meta(tmp_path, monkeypatch):
    """`session_start` отдаёт ruleset_hash, режим дистрибуции, бандлы и warnings."""
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(tmp_path / "trivy"))
    monkeypatch.setenv("APPSECGATE_MCP_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(server, "_session", server.SessionState())

    out = await server.session_start(str(tmp_path))

    assert out["status"] == "ready"
    assert isinstance(out["ruleset_hash"], str)
    assert out["ruleset_hash"].startswith("sha256:")
    assert out["distribution_mode"] == "mit"
    assert isinstance(out["bundles"], list)
    assert isinstance(out["warnings"], list)
    assert out["ruleset_version"] is not None


async def test_scan_output_carries_ruleset_hash(tmp_path):
    """`meta.ruleset_hash` каждого скана совпадает с хэшем разрешённых правил."""
    from appsecgate_mcp.rules.resolver import ResolvedRules

    state = server.SessionState()
    state.config = Config()
    state.config.resolved_rules = ResolvedRules(ruleset_hash="sha256:testhash")

    output = await server._build_scan_output(state, ScanResult())

    assert output["meta"]["ruleset_hash"] == "sha256:testhash"
