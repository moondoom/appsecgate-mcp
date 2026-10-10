"""Общие фикстуры тестов SecGate MCP."""

from __future__ import annotations

from pathlib import Path

import pytest

from secgate_mcp.config.models import Config


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """Временный корень проекта с одним файлом."""
    (tmp_path / "app.py").write_text("print('hello')\n")
    return tmp_path


@pytest.fixture()
def default_config(project_dir: Path) -> Config:
    config = Config()
    config.project_path = str(project_dir)
    config.data_dir = str(project_dir / ".data")
    config.cache_dir = str(project_dir / ".cache")
    return config
