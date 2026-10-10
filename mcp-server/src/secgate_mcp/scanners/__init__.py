"""Scanner Adapter Layer: изолированные адаптеры сканеров."""

from secgate_mcp.scanners.base import BaseScanner, RawFinding
from secgate_mcp.scanners.gitleaks import GitleaksAdapter
from secgate_mcp.scanners.registry import ScannerRegistry
from secgate_mcp.scanners.runner import CommandResult, ScannerExecutionError, run_subprocess
from secgate_mcp.scanners.semgrep import SemgrepAdapter
from secgate_mcp.scanners.trivy import TrivyAdapter
from secgate_mcp.scanners.trufflehog import TruffleHogAdapter

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
