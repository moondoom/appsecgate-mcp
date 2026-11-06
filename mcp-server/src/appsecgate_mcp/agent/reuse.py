from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.models import AgentConfig

_EPOCH = datetime.min.replace(tzinfo=UTC)
_VERDICTS = {"TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"}
_QUERY = """
SELECT fp, verdict_id, verdict, explanation, confidence, created_at, at
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


def _confidence(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, str) and value.isdigit():
        candidate = int(value)
    else:
        return None
    return candidate if 0 <= candidate <= 100 else None


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


async def reuse_prior_verdicts(
    config: AgentConfig,
    controller: AgentController,
    stats: dict[str, int],
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
        reuse_ttl_seconds=config.reuse_ttl_seconds,
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
        confidence = _confidence(row.get("confidence"))
        timestamp = _timestamp(row)
        age = (current - timestamp).total_seconds() if timestamp is not None else None
        fresh = confidence is not None and age is not None and 0 <= age < config.reuse_ttl_seconds
        if fresh:
            reused.append(
                {
                    "finding_id": finding_id,
                    "verdict": row["verdict"],
                    "explanation": f"Reused prior verdict: {row.get('explanation') or ''}",
                    "confidence": confidence,
                }
            )
            continue
        reason = "legacy_confidence_missing" if confidence is None else "ttl_expired"
        stats["reevaluated_verdicts"] += 1
        stats[f"reevaluated_{reason}"] += 1
        controller.revisions[finding_id] = {
            "supersedes_verdict_id": str(row.get("verdict_id") or "") or None,
            "revision_reason": reason,
        }
    if not reused:
        return
    result = await controller.execute("submit_verdicts", {"verdicts": reused}, record=False)
    stats["reused_verdicts"] = result.get("accepted", 0)
