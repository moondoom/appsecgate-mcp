from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: Path
    project_id: str | None = None
    data_dir: Path
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    mode: Literal["ro"] = "ro"
    agent_mode: Literal["free", "guided"] = "guided"
    scan: Literal["full", "diff"] = "full"
    policy: Literal["warn", "block"] = "warn"
    output_format: Literal["markdown", "json"] = "markdown"
    llm_url: str
    llm_model: str
    llm_api_key: str = "local"
    llm_timeout: float = 120
    llm_failure_timeout: float = 600
    llm_temperature: float = 0
    llm_top_p: float = 1
    llm_max_tokens: int = 2048
    llm_num_ctx: int = 32768
    internal_parallel: int = Field(default=2, ge=1)
    batch_sort: Literal["mode_major", "none"] = "mode_major"
    mode_batch_sizes: dict[str, int] = Field(default_factory=dict)
    adaptive_max_tokens: bool = False
    adaptive_max_tokens_cap: int = 4096
    mode_b: bool = False
    timeout: float = 1800
    max_iterations: int = 50
    max_restarts: int = 3
    max_compactions: int = 5
    max_tokens: int = 500_000
    max_context_chars: int = 120_000
    master_url: str | None = None
    master_api_key: str | None = None
    knowledge_cutoff: str | None = None
    no_master_knowledge: bool = False
    no_sync: bool = False
    reuse_verdicts: bool = True
    reuse_ttl_seconds: int = Field(default=604800, ge=0)
    force_reevaluate: bool = False
    ruleset_hash: str | None = None

    @property
    def prompt_path(self) -> Path:
        if self.agent_mode == "guided":
            return self.guided_prompt_path
        return Path(__file__).parent / "prompts" / "agent_system.md"

    @property
    def guided_prompt_path(self) -> Path:
        return Path(__file__).parent / "prompts" / "agent_guided.md"

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt_path.read_bytes()).hexdigest()

    def prompt_sha256_for_mode(self, mode: str) -> str:
        path = Path(__file__).parent / "prompts" / f"agent_{mode}.md"
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def system_prompt_for_modes(self, modes: set[str]) -> str:
        parts = [self.guided_prompt_path.read_text(encoding="utf-8")]
        for mode in sorted(modes):
            path = Path(__file__).parent / "prompts" / f"agent_{mode}.md"
            parts.append(path.read_text(encoding="utf-8"))
        return "\n\n".join(parts)


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    verdict: Literal["TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"]
    explanation: str = ""
    confidence_level: Literal["high", "medium", "low", "speculative"] | None = None
    evidence_basis: (
        Literal[
            "direct_snippet",
            "direct_snippet_credential",
            "file_verified",
            "indirect_pattern",
            "test_or_fixture",
            "assumption",
            "placeholder_or_example",
            "manifest_version_match",
            "reachability_verified",
            "reachability_unverified",
            "cve_reference_only",
            "vex_upstream",
            "manifest_absent",
            "policy_rule_direct",
            "policy_rule_context",
            "override_possible",
            "hallucination_risk",
            "deployment_verified",
        ]
        | None
    ) = None
    evidence_quote: str = ""
    source_file: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    read_event_id: str | None = None
    quote_hash: str | None = None
    reasoning: str = ""
    model_confidence_level: Literal["high", "medium", "low", "speculative"] | None = None
    model_verdict: Literal["TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"] | None = None
    downgrade_reason: str | None = None
    failure_reason: (
        Literal["context_overflow", "timeout", "llm_error", "budget_exhausted"] | None
    ) = None
    failure_detail: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    patch: str | list[dict[str, Any]] | None = None
    supersedes_verdict_id: str | None = Field(default=None, exclude=True)
    revision_reason: Literal[
        "initial",
        "ttl_expired",
        "legacy_confidence_missing",
        "manual",
        "prompt_updated",
        "ruleset_updated",
    ] = Field(default="initial", exclude=True)


class LlmResult(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
