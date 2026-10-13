"""Запуск внешних сканеров через subprocess без shell.

Без shell — обязательно для безопасности (нет `sh -c` и потенциального
инъекционного исполнения). Все вызовы — async через `asyncio.to_thread`
по тем же причинам, что и sqlite: не блокировать event loop.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from appsecgate_mcp.normalization.redactor import redact_text

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Результат завершения внешней команды."""

    returncode: int
    stdout: str
    stderr: str
    cmd: list[str] = field(default_factory=list)  # original command, useful for errors


class ScannerExecutionError(RuntimeError):
    """Поднимается адаптером, когда сканер не может быть запущен."""

    def __init__(self, scanner: str, message: str) -> None:
        super().__init__(message)
        self.scanner = scanner


async def run_subprocess(
    cmd: list[str],
    *,
    timeout: float | int = 120,
    cwd: str | Path | None = None,
) -> CommandResult:
    """Запускает команду без shell и возвращает её stdout/stderr/returncode.

    Исключения `FileNotFoundError` и `TimeoutExpired` передаются как
    `ScannerExecutionError` — адаптеры не должны перехватывать их
    самостоятельно.
    """

    argv_display = redact_text(" ".join(cmd))
    started = time.perf_counter()
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=float(timeout),
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.warning("spawn not_found duration_ms=%s cmd=%s", duration_ms, argv_display)
        raise ScannerExecutionError(
            scanner="unknown",
            message=f"binary not found: {cmd[0] if cmd else '<empty command>'}",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.warning("spawn timeout duration_ms=%s cmd=%s", duration_ms, argv_display)
        raise ScannerExecutionError(
            scanner="unknown",
            message=f"timeout after {timeout}s: {' '.join(cmd)}",
        ) from exc

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    outcome = "ok" if proc.returncode == 0 else "nonzero_exit"
    logger.info(
        "spawn %s duration_ms=%s returncode=%s stdout_bytes=%s stderr_bytes=%s cwd=%s cmd=%s",
        outcome,
        duration_ms,
        proc.returncode,
        len(stdout),
        len(stderr),
        str(cwd) if cwd is not None else "",
        argv_display,
    )
    if stderr.strip():
        # Хвост stderr редактуется: в stderr сканеров могут быть фрагменты секретов.
        logger.info("stderr tail (%d bytes): %s", len(stderr), redact_text(stderr)[-2000:])

    return CommandResult(
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        cmd=cmd,
    )
