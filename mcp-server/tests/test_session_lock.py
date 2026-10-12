"""Этап 2: параллельная инициализация сессии выполняется один раз."""

from __future__ import annotations

import asyncio

import pytest

from appsecgate_mcp import server
from appsecgate_mcp.config.loader import ConfigLoader


@pytest.fixture
def fresh_session(tmp_path, monkeypatch):
    """Изолированная сессия: без сети, без /etc/appsecgate и без домашнего каталога."""
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("APPSECGATE_MCP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(tmp_path / "trivy"))
    state = server.SessionState()
    state.project_path = str(root)
    state.config_loader = ConfigLoader(tmp_path / "no-default.yaml")
    monkeypatch.setattr(server, "_session", state)
    return state


@pytest.fixture
def init_counter(monkeypatch):
    """Считает вызовы init_databases, оставляя реальное поведение."""
    real = server.init_databases
    calls: list[int] = []

    async def counting(paths):
        calls.append(1)
        await asyncio.sleep(0)  # отдаём управление, чтобы гонка была реальной
        return await real(paths)

    monkeypatch.setattr(server, "init_databases", counting)
    return calls


async def test_parallel_ensure_session_initializes_once(fresh_session, init_counter):
    results = await asyncio.gather(*(server._ensure_session() for _ in range(5)))

    assert all(r is fresh_session for r in results)
    assert fresh_session.initialized is True
    assert len(init_counter) == 1


async def test_initialize_without_force_is_noop_when_ready(fresh_session, init_counter):
    await fresh_session.initialize()
    await fresh_session.initialize()

    assert len(init_counter) == 1


async def test_force_reinitialize_runs_again(fresh_session, init_counter):
    await fresh_session.initialize()
    await fresh_session.initialize(force=True)

    assert len(init_counter) == 2
    assert fresh_session.initialized is True


async def test_initialize_locked_does_not_deadlock_when_called_under_lock(fresh_session):
    async with fresh_session._lock:
        await asyncio.wait_for(
            fresh_session._initialize_locked(None, force=False),
            timeout=5,
        )

    assert fresh_session.initialized is True
