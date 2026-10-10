"""Запуск внешних сканеров через subprocess без shell.

Без shell — обязательно для безопасности (нет `sh -c` и потенциального
инъекционного исполнения). Все вызовы — async через `asyncio.to_thread`
по тем же причинам, что и sqlite: не блокировать event loop.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


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

    async def _inner() -> CommandResult:
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
            raise ScannerExecutionError(
                scanner="unknown",
                message=f"binary not found: {cmd[0] if cmd else '<empty command>'}",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ScannerExecutionError(
                scanner="unknown",
                message=f"timeout after {timeout}s: {' '.join(cmd)}",
            ) from exc

        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            cmd=cmd,
        )

    return await _inner()
