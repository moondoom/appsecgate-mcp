from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: Path
    project_id: str | None = None
    data_dir: Path
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    mode: Literal["ro"] = "ro"
    agent_mode: Literal["free", "guided", "guided-sched"] = "free"
    scan: Literal["full", "diff"] = "full"
    policy: Literal["warn", "block"] = "warn"
    output_format: Literal["markdown", "json"] = "markdown"
    llm_url: str
    llm_model: str
    llm_api_key: str = "local"
    llm_timeout: float = 120
    llm_temperature: float = 0
    llm_top_p: float = 1
    llm_max_tokens: int = 2048
    llm_num_ctx: int = 32768
    sched_parallel: int = 2
    sched_lanes: list[int] = Field(default_factory=lambda: [8192, 16384, 32768])
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

    @property
    def prompt_path(self) -> Path:
        if self.agent_mode in ("guided", "guided-sched"):
            return self.guided_prompt_path
        return Path(__file__).parent / "prompts" / "agent_system.md"

    @property
    def guided_prompt_path(self) -> Path:
        return Path(__file__).parent / "prompts" / "agent_guided.md"

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt_path.read_bytes()).hexdigest()


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    verdict: Literal["TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"]
    explanation: str = ""
    confidence: int | None = Field(default=None, ge=0, le=100)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    patch: str | list[dict[str, Any]] | None = None
    supersedes_verdict_id: str | None = Field(default=None, exclude=True)
    revision_reason: Literal["initial", "ttl_expired", "legacy_confidence_missing", "manual"] = (
        Field(default="initial", exclude=True)
    )

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100:
            return value
        return None


class LlmResult(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
