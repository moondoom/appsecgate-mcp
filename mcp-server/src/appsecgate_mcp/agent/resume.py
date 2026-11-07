from __future__ import annotations

import json
import os
from typing import Any

from pydantic import ValidationError

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.models import AgentConfig, Verdict

_FIELDS = (
    "verdict",
    "explanation",
    "confidence_level",
    "evidence_basis",
    "evidence_quote",
    "source_file",
    "start_line",
    "end_line",
    "read_event_id",
    "quote_hash",
    "reasoning",
    "model_confidence_level",
    "model_verdict",
    "downgrade_reason",
    "failure_reason",
    "failure_detail",
    "evidence",
)


def resume_enabled() -> bool:
    return os.environ.get("APPSECGATE_AGENT_RESUME_JOURNAL", "1") != "0"


def resume_from_journal(config: AgentConfig, controller: AgentController) -> int:
    """Re-accept verdicts already journaled in this data dir (GD-14).

    Same-run continuity after a container restart/timeout: the append-only
    triage journal is durable, so the latest row per fingerprint is restored
    without an LLM call. Rows outside the current inventory are skipped, so
    a rescan with a different inventory simply resumes nothing. This is not
    cross-run reuse (GD-10): no TTL, no ruleset check — the rows were
    produced by this same run id.
    """
    if not resume_enabled():
        return 0
    path = config.data_dir / "triage_verdicts.ndjson"
    if not path.exists():
        return 0
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event_type") != "triage_verdicted":
            continue
        fp = row.get("fp")
        if fp and row.get("verdict"):
            latest[fp] = row
    resumed = 0
    for fp, row in latest.items():
        if fp not in controller.pending:
            continue
        data = {"finding_id": fp}
        for key in _FIELDS:
            if row.get(key) is not None:
                data[key] = row[key]
        try:
            verdict = Verdict.model_validate(data)
        except ValidationError:
            continue
        controller.verdicts[fp] = verdict
        controller.pending.discard(fp)
        resumed += 1
    return resumed
