"""Scanner Adapter Layer: изолированные адаптеры сканеров."""

from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.gitleaks import GitleaksAdapter
from appsecgate_mcp.scanners.registry import ScannerRegistry
from appsecgate_mcp.scanners.runner import CommandResult, ScannerExecutionError, run_subprocess
from appsecgate_mcp.scanners.semgrep import SemgrepAdapter
from appsecgate_mcp.scanners.trivy import TrivyAdapter
from appsecgate_mcp.scanners.trufflehog import TruffleHogAdapter

__all__ = [
    "BaseScanner",
    "CommandResult",
    "GitleaksAdapter",
    "RawFinding",
    "ScannerExecutionError",
    "ScannerRegistry",
    "SemgrepAdapter",
    "TrivyAdapter",
    "TruffleHogAdapter",
    "run_subprocess",
]
