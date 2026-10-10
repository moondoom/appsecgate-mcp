"""Тесты сборки ScannerRegistry из конфига."""

from __future__ import annotations

from appsecgate_mcp.config.models import Config
from appsecgate_mcp.scanners.registry import ScannerRegistry


def test_all_categories_built(default_config: Config):
    registry = ScannerRegistry.from_config(default_config, project_path=default_config.project_path)
    # sast=semgrep, secrets=gitleaks, sca+iac=trivy (схлопнуты)
    assert set(registry.names()) == {"semgrep", "gitleaks", "trivy"}
    assert len(registry) == 3
    assert "trivy" in registry


def test_disabled_category_skipped(default_config: Config):
    default_config.scanners.sast.enabled = False
    registry = ScannerRegistry.from_config(default_config, project_path=default_config.project_path)
    assert "semgrep" not in registry
    assert "gitleaks" in registry


def test_duplicate_tool_collapsed(default_config: Config):
    registry = ScannerRegistry.from_config(default_config, project_path=default_config.project_path)
    # sca и iac оба trivy — в реестре ровно один экземпляр
    assert registry.names().count("trivy") == 1
