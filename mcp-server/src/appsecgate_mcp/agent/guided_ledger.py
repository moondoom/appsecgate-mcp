from __future__ import annotations

import json
from typing import Any

from appsecgate_mcp.agent.models import AgentConfig


def _percentile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    return sorted_values[min(len(sorted_values) - 1, round(q * (len(sorted_values) - 1)))]


def charge_reserved(reserved: dict[str, int], chunk: list[str], request_tokens: int) -> None:
    """Charge a reserved-token share of one sent request to every finding in the chunk.

    Reserved charge (estimate + output reserve), never provider usage
    (ADR-0020 §3.5); cumulative across retries and splits.
    """
    share = -(-request_tokens // len(chunk))
    for finding_id in chunk:
        reserved[finding_id] = reserved.get(finding_id, 0) + share


def write_reserved_ledger(config: AgentConfig, reserved: dict[str, int]) -> dict[str, Any]:
    """Persist the per-finding reserved-token ledger and return summary stats."""
    if not reserved:
        return {}
    ledger_path = config.data_dir / "reserved_tokens.ndjson"
    with ledger_path.open("w", encoding="utf-8") as output:
        for finding_id in sorted(reserved):
            output.write(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": config.run_id,
                        "fp": finding_id,
                        "reserved_tokens": reserved[finding_id],
                    }
                )
                + "\n"
            )
    ordered = sorted(reserved.values())
    return {
        "reserved_tokens_total": sum(ordered),
        "reserved_tokens_p50": _percentile(ordered, 0.50),
        "reserved_tokens_p95": _percentile(ordered, 0.95),
        "reserved_tokens_p99": _percentile(ordered, 0.99),
        "reserved_tokens_max": ordered[-1],
    }
