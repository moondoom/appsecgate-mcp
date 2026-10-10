"""Модели предметной области SecGate MCP."""

from secgate_mcp.models.finding import (
    Finding,
    FixResult,
    ScanMeta,
    ScanResult,
    Severity,
    Suppression,
)

__all__ = [
    "Finding",
    "FixResult",
    "ScanMeta",
    "ScanResult",
    "Severity",
    "Suppression",
]
