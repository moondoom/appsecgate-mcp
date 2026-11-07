from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from appsecgate_mcp.agent.models import AgentConfig
from appsecgate_mcp.normalization.redactor import redact_text

_CACHE_COUNTER_KEYS = ("cache_read_tokens", "prompt_cache_hit_tokens")


class CallJournal:
    """Per-LLM-call telemetry for guided runs (ADR-0019 §1.4.3)."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.path = config.data_dir / "llm_calls.ndjson"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_metrics_unavailable = False

    def append(
        self,
        *,
        batch_id: str,
        mode: str,
        started_monotonic: float,
        ended_monotonic: float,
        started_at: datetime,
        usage: dict[str, Any] | None,
        failure_reason: str | None = None,
        failure_detail: str | None = None,
    ) -> dict[str, Any]:
        usage = usage or {}
        cache = {key: usage.get(key) for key in _CACHE_COUNTER_KEYS}
        if all(value is None for value in cache.values()):
            self.cache_metrics_unavailable = True
        record = {
            "schema_version": 1,
            "run_id": self.config.run_id,
            "project_id": self.config.project_id or "",
            "process_id": os.getpid(),
            "agent_mode": self.config.agent_mode,
            "batch_id": batch_id,
            "mode": mode,
            "num_ctx": self.config.llm_num_ctx,
            "model": self.config.llm_model,
            "start_ts": started_at.isoformat(),
            "end_ts": datetime.now(UTC).isoformat(),
            "wall_ms": int((ended_monotonic - started_monotonic) * 1000),
            "ttft_ms": None,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "prompt_eval_count": usage.get("prompt_eval_count"),
            "prompt_eval_duration": usage.get("prompt_eval_duration"),
            "cache_read_tokens": cache["cache_read_tokens"],
            "prompt_cache_hit_tokens": cache["prompt_cache_hit_tokens"],
            "slot_id": None,
            "reused": False,
            "revision_reason": None,
            "failure_reason": failure_reason,
            "failure_detail": redact_text(failure_detail) if failure_detail else None,
        }
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record
