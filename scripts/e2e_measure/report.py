"""Data-контейнеры E2E-отчёта: E2eResult, E2eReport."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("e2e_measure")


@dataclass
class E2eResult:
    test_name: str
    status: str = "PASS"  # PASS | FAIL | SKIP
    duration_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class E2eReport:
    timestamp: str = ""
    project_path: str = ""
    results: list[E2eResult] = field(default_factory=list)

    def add(self, result: E2eResult) -> None:
        self.results.append(result)
        icon = "✅" if result.status == "PASS" else ("❌" if result.status == "FAIL" else "⏭️")
        logger.info("%s %s (%s ms)", icon, result.test_name, round(result.duration_ms, 1))
        if result.error:
            logger.warning("  ⚠️  %s", result.error)

    def summary(self) -> dict[str, Any]:
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        skipped = sum(1 for r in self.results if r.status == "SKIP")
        return {
            "total": len(self.results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "success_rate": f"{passed / max(len(self.results), 1) * 100:.1f}%",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "project_path": self.project_path,
            "summary": self.summary(),
            "results": [
                {
                    "test": r.test_name,
                    "status": r.status,
                    "duration_ms": round(r.duration_ms, 1),
                    "error": r.error,
                    "details": r.details,
                }
                for r in self.results
            ],
        }
