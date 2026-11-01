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
    scan: Literal["full", "diff"] = "full"
    policy: Literal["warn", "block"] = "warn"
    output_format: Literal["markdown", "json"] = "markdown"
    llm_url: str
    llm_model: str
    llm_api_key: str = "local"
    llm_timeout: float = 120
    timeout: float = 1800
    max_iterations: int = 50
    max_tokens: int = 500_000
    max_context_chars: int = 120_000
    master_url: str | None = None
    master_api_key: str | None = None
    no_sync: bool = False

    @property
    def prompt_path(self) -> Path:
        return Path(__file__).parent / "prompts" / "agent_system.md"

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt_path.read_bytes()).hexdigest()


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    verdict: Literal["TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"]
    explanation: str = ""
    patch: str | list[dict[str, Any]] | None = None


class LlmResult(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
