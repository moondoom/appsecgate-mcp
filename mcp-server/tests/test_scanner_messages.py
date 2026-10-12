"""Тесты редактирования абсолютного корня проекта в сообщениях сканеров."""

from __future__ import annotations

from pathlib import Path

from appsecgate_mcp.scanners.base import BaseScanner


class _DummyScanner(BaseScanner):
    async def scan(self, files: list[str], mode: str) -> list:
        return []

    async def is_available(self) -> bool:
        return True


def test_redact_replaces_root_with_relative_path(tmp_path: Path) -> None:
    scanner = _DummyScanner(project_path=str(tmp_path))
    text = f"semgrep: failed on {tmp_path}/src/app.py"
    assert scanner.redact_project_root(text) == "semgrep: failed on src/app.py"


def test_redact_bare_root_becomes_dot(tmp_path: Path) -> None:
    scanner = _DummyScanner(project_path=str(tmp_path))
    text = f"scan of {tmp_path} finished"
    assert scanner.redact_project_root(text) == "scan of . finished"


def test_redact_ignores_sibling_prefix(tmp_path: Path) -> None:
    scanner = _DummyScanner(project_path=str(tmp_path))
    text = f"{tmp_path}2/secret.py"
    assert scanner.redact_project_root(text) == text


def test_redact_empty_and_plain_text(tmp_path: Path) -> None:
    scanner = _DummyScanner(project_path=str(tmp_path))
    assert scanner.redact_project_root("") == ""
    assert scanner.redact_project_root("no paths here") == "no paths here"