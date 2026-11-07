from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.models import AgentConfig

_EPOCH = datetime.min.replace(tzinfo=UTC)
_VERDICTS = {"TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"}
_LEVELS = {"high", "medium", "low", "speculative"}
_QUERY = """
SELECT fp, verdict_id, verdict, explanation, confidence_level, evidence_basis,
       evidence_quote, source_file, start_line, end_line, read_event_id, quote_hash,
       reasoning, prompt_mode, prompt_sha256, ruleset_hash, verdict_source,
       created_at, at
FROM v_triage_verdicts WHERE project_key = ?
""".strip()


def _timestamp(row: dict[str, Any]) -> datetime | None:
    value = row.get("created_at") or row.get("at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _latest_rows(rows: list[dict[str, Any]], pending: set[str]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        finding_id = row.get("fp")
        if finding_id not in pending or row.get("verdict") not in _VERDICTS:
            continue
        key = (_timestamp(row) or _EPOCH, str(row.get("verdict_id") or ""))
        previous = latest.get(finding_id)
        if previous is None:
            latest[finding_id] = row
            continue
        previous_key = (
            _timestamp(previous) or _EPOCH,
            str(previous.get("verdict_id") or ""),
        )
        if key > previous_key:
            latest[finding_id] = row
    return latest


def _record_decision(
    controller: AgentController,
    stats: dict[str, Any],
    finding_id: str,
    *,
    decision: str,
    reason: str,
) -> None:
    reasons = stats.setdefault("reuse_reasons", {})
    reasons[reason] = reasons.get(reason, 0) + 1
    controller.action_log.append(
        {
            "tool": "reuse_prior_verdicts",
            "status": decision,
            "finding_id": finding_id,
            "reuse_reason": reason,
            "reuse_saved_tokens": None,
        }
    )


async def reuse_prior_verdicts(
    config: AgentConfig,
    controller: AgentController,
    stats: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    if not (config.reuse_verdicts and config.master_url and not config.no_master_knowledge):
        return
    stats.update(
        reuse_candidates=0,
        reused_verdicts=0,
        reevaluated_verdicts=0,
        reevaluated_ttl_expired=0,
        reevaluated_legacy_confidence_missing=0,
        reevaluated_prompt_updated=0,
        reevaluated_ruleset_updated=0,
        human_verdicts_protected=0,
        reuse_ttl_seconds=config.reuse_ttl_seconds,
        reuse_saved_tokens=None,
        reuse_saved_tokens_known=False,
    )
    response = await controller.execute(
        "master_query_findings_db", {"sql": _QUERY, "params": [controller.project_id]}
    )
    rows = response.get("rows") or response.get("result") or []
    latest = _latest_rows(rows, controller.pending)
    current = now or datetime.now(UTC)
    reused: list[dict[str, Any]] = []
    for finding_id in controller.finding_ids:
        row = latest.get(finding_id)
        if row is None:
            continue
        stats["reuse_candidates"] += 1
        if row.get("verdict_source") == "human":
            stats["human_verdicts_protected"] += 1
            controller.pending.discard(finding_id)
            _record_decision(
                controller,
                stats,
                finding_id,
                decision="protected",
                reason="human_verdict",
            )
            continue
        confidence_level = row.get("confidence_level")
        timestamp = _timestamp(row)
        age = (current - timestamp).total_seconds() if timestamp is not None else None
        mode = controller.finding_modes.get(finding_id, "sast")
        prompt_matches = row.get("prompt_sha256") == config.prompt_sha256_for_mode(mode)
        ruleset_matches = bool(config.ruleset_hash) and row.get("ruleset_hash") == (
            config.ruleset_hash
        )
        fresh = (
            ruleset_matches
            and confidence_level in _LEVELS
            and prompt_matches
            and age is not None
            and 0 <= age < config.reuse_ttl_seconds
        )
        if fresh:
            reused_item = {
                "finding_id": finding_id,
                "verdict": row["verdict"],
                "explanation": f"Reused prior verdict: {row.get('explanation') or ''}",
            }
            for key in (
                "confidence_level",
                "evidence_basis",
                "evidence_quote",
                "source_file",
                "start_line",
                "end_line",
                "read_event_id",
                "quote_hash",
                "reasoning",
            ):
                if row.get(key) is not None:
                    reused_item[key] = row[key]
            reused.append(reused_item)
            _record_decision(
                controller,
                stats,
                finding_id,
                decision="reused",
                reason="fresh_matching_context",
            )
            continue
        if not ruleset_matches:
            reason = "ruleset_updated"
        elif not prompt_matches:
            reason = "prompt_updated"
        elif confidence_level not in _LEVELS:
            reason = "legacy_confidence_missing"
        else:
            reason = "ttl_expired"
        stats["reevaluated_verdicts"] += 1
        stats[f"reevaluated_{reason}"] += 1
        controller.revisions[finding_id] = {
            "supersedes_verdict_id": str(row.get("verdict_id") or "") or None,
            "revision_reason": reason,
        }
        _record_decision(
            controller,
            stats,
            finding_id,
            decision="reevaluate",
            reason=reason,
        )
    if not reused:
        return
    result = await controller.execute("submit_verdicts", {"verdicts": reused}, record=False)
    stats["reused_verdicts"] = result.get("accepted", 0)
