"""Конфигурация SecGate MCP: модели, загрузка и deep-merge."""

from secgate_mcp.config.loader import ConfigLoader
from secgate_mcp.config.models import Config, GatesConfig, ScannerConfig

__all__ = ["Config", "ConfigLoader", "GatesConfig", "ScannerConfig"]
