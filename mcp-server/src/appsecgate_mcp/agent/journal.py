from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from appsecgate_mcp.agent.models import AgentConfig, Verdict
from appsecgate_mcp.normalization.redactor import redact_text

_NAMESPACE = uuid.UUID("c54b1c08-d93d-4f0a-bb4d-c438ea93a2d8")


def _safe(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    return value


class TriageJournal:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.project_id = config.project_id or ""
        self.path = config.data_dir / "triage_verdicts.ndjson"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def append(self, verdict: Verdict) -> Verdict:
        sanitized = verdict.model_copy(
            update={
                "explanation": redact_text(verdict.explanation),
                "evidence": _safe(verdict.evidence),
                "patch": None,
            }
        )
        verdict_id = str(
            uuid.uuid5(
                _NAMESPACE,
                f"{self.project_id}:{self.config.run_id}:{sanitized.finding_id}:model",
            )
        )
        created_at = datetime.now(UTC).isoformat()
        event = {
            "schema_version": 1,
            "client_event_id": verdict_id,
            "project_key": self.project_id,
            "event_type": "triage_verdicted",
            "at": created_at,
            "fp": sanitized.finding_id,
            "verdict_id": verdict_id,
            "run_id": self.config.run_id,
            "verdict": sanitized.verdict,
            "verdict_source": "model",
            "review_status": "unreviewed",
            "explanation": sanitized.explanation,
            "evidence": sanitized.evidence,
            "agent_version": "autonomous-v1",
            "model": self.config.llm_model,
            "prompt_sha256": self.config.prompt_sha256,
            "created_at": created_at,
        }
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        return sanitized
