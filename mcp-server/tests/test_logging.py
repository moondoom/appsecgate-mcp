"""Тесты логирования и диагностики запуска внешних команд.

Покрывают: запись ``returncode``/``duration_ms``, редакцию секретов в argv и
stderr, исходы ``not_found``/``timeout``, настройку уровня и файла лога.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import pytest

from appsecgate_mcp.logging_setup import LOG_LEVEL_DEFAULT, configure_logging
from appsecgate_mcp.scanners.runner import ScannerExecutionError, run_subprocess


@pytest.fixture(autouse=True)
def _reset_appsecgate_logger():
    """Изолирует состояние логгера ``appsecgate_mcp`` между тестами."""
    logger = logging.getLogger("appsecgate_mcp")
    yield
    logger.setLevel(logging.NOTSET)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


async def test_run_subprocess_logs_success(caplog):
    caplog.set_level(logging.INFO, logger="appsecgate_mcp.scanners.runner")
    result = await run_subprocess([sys.executable, "-c", "pass"], timeout=30)
    assert result.returncode == 0
    assert "returncode=0" in caplog.text
    assert "duration_ms=" in caplog.text
    assert "stdout_bytes=0" in caplog.text


async def test_run_subprocess_redacts_secrets(caplog):
    caplog.set_level(logging.INFO, logger="appsecgate_mcp.scanners.runner")
    script = "import sys; sys.stderr.write('password=SuperSecret123456789')"
    await run_subprocess([sys.executable, "-c", script], timeout=30)
    assert "SuperSecret123456789" not in caplog.text
    assert "[REDACTED]" in caplog.text


async def test_run_subprocess_not_found_logged(caplog):
    caplog.set_level(logging.INFO, logger="appsecgate_mcp.scanners.runner")
    with pytest.raises(ScannerExecutionError):
        await run_subprocess(["appsecgate-definitely-missing-binary"], timeout=5)
    assert "not_found" in caplog.text


async def test_run_subprocess_timeout_logged(caplog):
    caplog.set_level(logging.INFO, logger="appsecgate_mcp.scanners.runner")
    script = "import time; time.sleep(5)"
    with pytest.raises(ScannerExecutionError):
        await run_subprocess([sys.executable, "-c", script], timeout=0.2)
    assert "timeout" in caplog.text


def test_configure_logging_defaults_to_info(monkeypatch):
    monkeypatch.delenv("APPSECGATE_LOG_LEVEL", raising=False)
    monkeypatch.delenv("APPSECGATE_LOG_FILE", raising=False)
    configure_logging()
    assert LOG_LEVEL_DEFAULT == "INFO"
    assert logging.getLogger("appsecgate_mcp").level == logging.INFO


def test_configure_logging_respects_env_level(monkeypatch):
    monkeypatch.setenv("APPSECGATE_LOG_LEVEL", "DEBUG")
    configure_logging()
    assert logging.getLogger("appsecgate_mcp").level == logging.DEBUG


def test_configure_logging_writes_file(tmp_path):
    log_file = tmp_path / "appsecgate.log"
    configure_logging(level="INFO", log_file=str(log_file))
    root = logging.getLogger("appsecgate_mcp")
    assert any(isinstance(h, RotatingFileHandler) for h in root.handlers)


def test_configure_logging_no_file_by_default(monkeypatch):
    monkeypatch.delenv("APPSECGATE_LOG_FILE", raising=False)
    configure_logging()
    root = logging.getLogger("appsecgate_mcp")
    assert not any(isinstance(h, RotatingFileHandler) for h in root.handlers)
