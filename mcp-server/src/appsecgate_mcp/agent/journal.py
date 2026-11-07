from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from appsecgate_mcp.agent.models import AgentConfig, Verdict
from appsecgate_mcp.agent.verdict_validator import finding_mode
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
    def __init__(
        self,
        config: AgentConfig,
        *,
        scan_meta: dict[str, Any] | None = None,
        findings: list[dict[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self.scan_meta = scan_meta or {}
        self.findings = {item["finding_id"]: item for item in findings or []}
        self.project_id = config.project_id or ""
        self.path = config.data_dir / "triage_verdicts.ndjson"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def append(self, verdict: Verdict) -> Verdict:
        sanitized = verdict.model_copy(
            update={
                "explanation": redact_text(verdict.explanation),
                "reasoning": redact_text(verdict.reasoning),
                "evidence_quote": redact_text(verdict.evidence_quote),
                "evidence": _safe(verdict.evidence),
                "failure_detail": redact_text(verdict.failure_detail or ""),
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
        finding = self.findings.get(sanitized.finding_id, {})
        prompt_mode = finding_mode(finding.get("category"))
        event = {
            "schema_version": 1,
            "client_event_id": verdict_id,
            "project_key": self.project_id,
            "event_type": "triage_verdicted",
            "at": created_at,
            "fp": sanitized.finding_id,
            "verdict_id": verdict_id,
            "supersedes_verdict_id": sanitized.supersedes_verdict_id,
            "revision_reason": sanitized.revision_reason,
            "run_id": self.config.run_id,
            "verdict": sanitized.verdict,
            "confidence_level": sanitized.confidence_level,
            "evidence_basis": sanitized.evidence_basis,
            "evidence_quote": sanitized.evidence_quote,
            "source_file": sanitized.source_file,
            "start_line": sanitized.start_line,
            "end_line": sanitized.end_line,
            "read_event_id": sanitized.read_event_id,
            "quote_hash": sanitized.quote_hash,
            "reasoning": sanitized.reasoning,
            "model_confidence_level": sanitized.model_confidence_level,
            "model_verdict": sanitized.model_verdict,
            "downgrade_reason": sanitized.downgrade_reason,
            "failure_reason": sanitized.failure_reason,
            "failure_detail": sanitized.failure_detail,
            "verdict_source": "model",
            "actor_id": f"model:{self.config.llm_model}",
            "review_status": "unreviewed",
            "explanation": sanitized.explanation,
            "evidence": sanitized.evidence,
            "agent_version": "autonomous-v1",
            "model": self.config.llm_model,
            "prompt_mode": prompt_mode,
            "prompt_sha256": self.config.prompt_sha256_for_mode(prompt_mode),
            "scanner": finding.get("scanner"),
            "rule_id": finding.get("rule_id"),
            "ruleset_hash": self.scan_meta.get("ruleset_hash"),
            "rule_hash": finding.get("rule_hash"),
            "rule_hash_status": finding.get("rule_hash_status", "unavailable"),
            "created_at": created_at,
        }
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        return sanitized
