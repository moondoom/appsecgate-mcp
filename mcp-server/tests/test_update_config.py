"""Этап 3: update_config валидирует конфиг до записи и откатывает файл при сбое."""

from __future__ import annotations

from pathlib import Path

import pytest

from appsecgate_mcp import server
from appsecgate_mcp.config.loader import ConfigLoader

INITIAL_YAML = "scanners:\n  sast:\n    enabled: true\n"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """Изолированный проект со свежей сессией: без сети и без /etc/appsecgate."""
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("APPSECGATE_MCP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(tmp_path / "trivy"))
    state = server.SessionState()
    state.project_path = str(root)
    state.config_loader = ConfigLoader(tmp_path / "no-default.yaml")
    monkeypatch.setattr(server, "_session", state)
    return root


def _config_file(root: Path) -> Path:
    return root / ".appsecgate-mcp" / "config.yaml"


def _write_initial(root: Path) -> Path:
    conf = _config_file(root)
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(INITIAL_YAML, encoding="utf-8")
    return conf


async def test_invalid_updates_keep_file_unchanged(project):
    conf = _write_initial(project)
    before = conf.read_text(encoding="utf-8")

    out = await server.update_config({"network": {"sync": {"timeout_seconds": "abc"}}})

    assert out["status"] == "invalid"
    assert out["errors"]
    assert any("timeout_seconds" in e for e in out["errors"])
    assert conf.read_text(encoding="utf-8") == before


async def test_invalid_updates_do_not_create_config_dir(project):
    conf = _config_file(project)

    out = await server.update_config({"network": {"sync": {"timeout_seconds": "abc"}}})

    assert out["status"] == "invalid"
    assert not conf.exists()
    assert not conf.parent.exists()


async def test_valid_updates_change_file(project):
    conf = _write_initial(project)

    out = await server.update_config({"scanners": {"sast": {"severity_threshold": "high"}}})

    assert out["status"] == "updated"
    assert "severity_threshold: high" in conf.read_text(encoding="utf-8")
    assert "enabled: true" in conf.read_text(encoding="utf-8")
    assert server._session.config.scanners.sast.severity_threshold == "high"


async def test_reinit_failure_rolls_back_file(project, monkeypatch):
    conf = _write_initial(project)
    before = conf.read_text(encoding="utf-8")

    # Первый вызов — ленивая инициализация сессии, второй — переинициализация
    # внутри update_config (падает), третий — откат (проходит).
    real_from_config = server.ScannerRegistry.from_config
    calls = {"n": 0}

    def flaky_from_config(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real_from_config(*args, **kwargs)

    monkeypatch.setattr(server.ScannerRegistry, "from_config", flaky_from_config)

    out = await server.update_config({"scanners": {"sast": {"severity_threshold": "high"}}})

    assert out["status"] == "error"
    assert "rolled back" in out["reason"]
    assert conf.read_text(encoding="utf-8") == before
    assert server._session.initialized is True


async def test_reinit_failure_removes_file_created_by_update(project, monkeypatch):
    conf = _config_file(project)

    real_from_config = server.ScannerRegistry.from_config
    calls = {"n": 0}

    def flaky_from_config(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real_from_config(*args, **kwargs)

    monkeypatch.setattr(server.ScannerRegistry, "from_config", flaky_from_config)

    out = await server.update_config({"scanners": {"sast": {"severity_threshold": "high"}}})

    assert out["status"] == "error"
    assert not conf.exists()


async def test_write_failure_leaves_no_temp_file(project, monkeypatch):
    conf = _write_initial(project)
    before = conf.read_text(encoding="utf-8")
    # Сессию инициализируем до подмены os.replace, чтобы не задеть её побочные эффекты.
    await server._ensure_session()

    def failing_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(server, "_replace_file", failing_replace)

    with pytest.raises(OSError, match="disk full"):
        await server.update_config({"scanners": {"sast": {"severity_threshold": "high"}}})

    assert conf.read_text(encoding="utf-8") == before
    assert list(conf.parent.glob("*.tmp")) == []


def test_atomic_write_replaces_content_and_leaves_no_tmp(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("old", encoding="utf-8")

    server._atomic_write(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob("*.tmp")) == []
