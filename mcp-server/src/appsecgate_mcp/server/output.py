"""Формирование ответов сканов: полный (scan_file/scan_diff) и announce (scan_project)."""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.models.finding import Finding, ScanResult
from appsecgate_mcp.orchestration.gate import GateSummary
from appsecgate_mcp.server.session import SessionState


def _by_file_top10(findings: list[Finding]) -> list[dict[str, Any]]:
    """Топ-10 файлов по числу находок (для announce-сводки scan_project)."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.file_path] = counts.get(f.file_path, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"file_path": fp, "count": n} for fp, n in ranked[:10]]


async def _build_announce_output(state: SessionState, result: ScanResult) -> dict[str, Any]:
    """Собирает announce-формат scan_project (arch §4.3)."""
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for f in result.findings:
        sev = f.severity.value
        by_severity[sev] = by_severity.get(sev, 0) + 1
        cat = f.category.value
        by_category[cat] = by_category.get(cat, 0) + 1

    ranked = sorted(result.findings, key=lambda f: f.sort_key(), reverse=True)
    top = ranked[:20]
    top_findings = [
        {
            "finding_id": f.fingerprint,
            "logical_id": None,
            "rule_id": f.rule_id,
            "file_path": f.file_path,
            "severity": f.severity.value,
            "scanner": f.scanner,
            "line_start": f.line_start,
        }
        for f in top
    ]

    return {
        "project": {
            "project_id": state.project_id,
            "project_alias": state.project_alias,
        },
        "summary": {
            "total": result.total,
            "by_severity": by_severity,
            "by_category": by_category,
            "by_file_top10": _by_file_top10(result.findings),
        },
        "top_findings": top_findings,
        "next_actions": [
            "query_findings_db(\"SELECT logical_id, severity FROM v_findings WHERE severity = 'high' LIMIT 50\")",
            "get_fix_context(finding_id='<finding_id>')",
            "get_fix_context_batch(finding_ids=['<id1>', '<id2>'])",
        ],
        "truncated": result.total > len(top_findings),
        "total_available": result.total,
    }


async def _build_scan_output(state: SessionState, result: ScanResult) -> dict[str, Any]:
    """Собирает сериализуемый ответ: сводка + findings + gate-решения + meta."""
    gate: GateSummary | None = None
    if state.gate_engine is not None:
        gate = await state.gate_engine.evaluate_all(result.findings, mode="local")
    # Хэш набора правил фиксируем в meta каждого скана (дизайн v1 §1.5).
    if state.config is not None and state.config.resolved_rules is not None:
        result.meta.ruleset_hash = state.config.resolved_rules.ruleset_hash
    meta = result.meta.model_dump(mode="json")
    # Trivy DB-предупреждения живут в meta.warnings (дизайн v1 §2.3, §4.4).
    if state.trivy_db is not None:
        for warning in state.trivy_db.collect_warnings():
            if warning not in meta["warnings"]:
                meta["warnings"].append(warning)
    payload: dict[str, Any] = {
        "summary": result.to_summary(),
        "findings": [f.model_dump(mode="json") for f in result.findings],
        "meta": meta,
    }
    if gate is not None:
        payload["gate"] = {
            "mode": gate.mode,
            "blocked": gate.block_count,
            "warned": len(gate.warned),
            "informed": len(gate.informed),
            "should_fail": gate.should_fail,
        }
    return payload
