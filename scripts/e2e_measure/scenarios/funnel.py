"""Сценарии E2E-воронки: замеры и проверки MCP-тулов."""

from __future__ import annotations

import time
from typing import Any

from e2e_measure.client import McpClient, _counts_total, _parse_result
from e2e_measure.report import E2eReport, E2eResult


async def measure_scan_project(client: McpClient, report: E2eReport) -> None:
    test = E2eResult(test_name="NF: scan_project duration")
    t0 = time.perf_counter()
    try:
        # scan_project() без аргументов (ADR-0005 §2.5, breaking change): отчёт counts.
        result = await client.call_tool("scan_project", {})
        dt = (time.perf_counter() - t0) * 1000
        test.duration_ms = dt
        payload = _parse_result(result)
        s = payload.get("counts", {})
        m = payload.get("meta", {})
        errs = m.get("errors", [])
        test.details = {
            "total_findings": _counts_total(payload),
            "counts": s,
            "meta_errors": errs,
            "meta_warnings": m.get("warnings", []),
            "duration_ms_raw": dt,
            "scan_mode": m.get("mode", "unknown"),
            "branch": m.get("branch"),
        }
        test.status = "FAIL" if errs else ("FAIL" if dt > 30000 else "PASS")
        if errs:
            test.error = f"meta.errors: {errs}"
        elif dt > 30000:
            test.error = f"duration_ms={dt:.0f} exceeds 30000"
    except Exception as exc:
        test.status = "FAIL"
        test.error = str(exc)
    report.add(test)


async def measure_scan_file(
    client: McpClient,
    report: E2eReport,
    file_path: str,
    expected_min: int = 1,
) -> dict[str, Any] | None:
    test = E2eResult(test_name=f"scan_file: {file_path}")
    t0 = time.perf_counter()
    try:
        result = await client.call_tool("scan_file", {"path": file_path})
        test.duration_ms = (time.perf_counter() - t0) * 1000
        payload = _parse_result(result)
        total = payload.get("summary", {}).get("total", 0)
        top = payload.get("top_findings", [])
        test.details = {
            "total": total,
            "severities": sorted({f.get("severity") for f in top if f.get("severity")}),
            "finding_ids": [
                f.get("finding_id", f.get("fingerprint", ""))[:12] + "..." for f in top
            ],
            "rule_ids": [f.get("rule_id") for f in top],
        }
        if total < expected_min:
            test.status = "FAIL"
            test.error = f"expected >= {expected_min}, got {total}"
        elif payload.get("meta", {}).get("errors"):
            test.status = "FAIL"
            test.error = f"meta.errors: {payload['meta']['errors']}"
        else:
            test.status = "PASS"
    except Exception as exc:
        test.status = "FAIL"
        test.error = str(exc)
    report.add(test)
    return payload if test.status == "PASS" else None


async def verify_fix_not_fixed(client: McpClient, report: E2eReport, finding_id: str) -> None:
    test = E2eResult(test_name=f"verify_fix: not_fixed ({finding_id[:12]}...)")
    t0 = time.perf_counter()
    try:
        result = await client.call_tool(
            "verify_fix",
            {
                "finding_id": finding_id,
                "status": "not_fixed",
                "note": "E2E test: file unchanged on :ro mount",
            },
        )
        test.duration_ms = (time.perf_counter() - t0) * 1000
        payload = _parse_result(result)
        test.details = {"response": payload}
        # Семантика сервера: status=ok (операция выполнена), verified_status —
        # результат перескана. not_fixed + verified=true = находка на месте.
        test.status = "PASS" if payload.get("verified_status") == "not_fixed" else "FAIL"
        if test.status == "FAIL":
            test.error = f"expected verified_status=not_fixed, got {payload}"
    except Exception as exc:
        test.status = "FAIL"
        test.error = str(exc)
    report.add(test)


async def suppress_and_rescan(
    client: McpClient, report: E2eReport, finding_id: str, fpath: str
) -> None:
    t1 = E2eResult(test_name=f"suppress_finding: ({finding_id[:12]}...)")
    t0 = time.perf_counter()
    try:
        result = await client.call_tool(
            "suppress_finding",
            {
                "finding_id": finding_id,
                "reason": "E2E test: suppression check",
            },
        )
        t1.duration_ms = (time.perf_counter() - t0) * 1000
        payload = _parse_result(result)
        t1.details = {"response": payload}
        t1.status = "PASS" if payload.get("status") == "suppressed" else "FAIL"
        if t1.status == "FAIL":
            t1.error = f"unexpected: {payload}"
    except Exception as exc:
        t1.status = "FAIL"
        t1.error = str(exc)
    report.add(t1)

    t2 = E2eResult(test_name=f"rescan after suppress: {fpath}")
    t0 = time.perf_counter()
    try:
        result = await client.call_tool("scan_file", {"path": fpath})
        t2.duration_ms = (time.perf_counter() - t0) * 1000
        t2.details["total"] = _parse_result(result).get("summary", {}).get("total", 0)
        t2.status = "PASS"
    except Exception as exc:
        t2.status = "FAIL"
        t2.error = str(exc)
    report.add(t2)


async def submit_feedback(client: McpClient, report: E2eReport, finding_id: str) -> None:
    test = E2eResult(test_name=f"submit_feedback: ({finding_id[:12]}...)")
    t0 = time.perf_counter()
    try:
        result = await client.call_tool(
            "submit_feedback",
            {
                "finding_id": finding_id,
                "type": "CONFIRMED",
                "reason": "E2E test: feedback check",
            },
        )
        test.duration_ms = (time.perf_counter() - t0) * 1000
        test.details = {"response": _parse_result(result)}
        test.status = "PASS"
    except Exception as exc:
        test.status = "FAIL"
        test.error = str(exc)
    report.add(test)


async def query_findings(client: McpClient, report: E2eReport) -> None:
    t1 = E2eResult(test_name="query_findings_db: SELECT v_findings")
    t0 = time.perf_counter()
    try:
        result = await client.call_tool(
            "query_findings_db", {"sql": "SELECT * FROM v_findings LIMIT 5"}
        )
        t1.duration_ms = (time.perf_counter() - t0) * 1000
        payload = _parse_result(result)
        rows = payload.get("rows", [])
        t1.details = {"row_count": len(rows), "columns": payload.get("columns", [])}
        t1.status = "PASS"
    except Exception as exc:
        t1.status = "FAIL"
        t1.error = str(exc)
    report.add(t1)

    t2 = E2eResult(test_name="query_findings_db: UPDATE rejected (invariant #5)")
    try:
        result = await client.call_tool(
            "query_findings_db",
            {
                "sql": "UPDATE v_findings SET status='SHOWN' WHERE 1=1",
            },
        )
        payload = _parse_result(result)
        t2.details = {"response": payload}
        # Сервер отвечает {"status": "error", "reason": "only SELECT ..."} — это
        # и есть ожидаемая блокировка (инвариант №5). MCP-клиент не бросает
        # исключение, поэтому проверяем status/error/isError.
        blocked = bool(
            payload.get("isError") or payload.get("error") or payload.get("status") == "error"
        )
        t2.status = "PASS" if blocked else "FAIL"
        if t2.status == "FAIL":
            t2.error = "UPDATE was not rejected — invariant #5 violated"
        else:
            t2.details["blocked_as_expected"] = True
    except Exception:
        t2.status = "PASS"
        t2.details = {"blocked_as_expected": True}
    report.add(t2)


async def get_scan_history_check(client: McpClient, report: E2eReport) -> None:
    test = E2eResult(test_name="get_scan_history")
    try:
        result = await client.call_tool("get_scan_history", {"limit": 50})
        payload = _parse_result(result)
        items = payload.get("items", []) or payload.get("findings", []) or []
        test.details = {"item_count": len(items)}
        test.status = "PASS" if items else "SKIP"
        if not items:
            test.error = "history is empty"
    except Exception as exc:
        test.status = "FAIL"
        test.error = str(exc)
    report.add(test)



async def export_snapshot_check(client: McpClient, report: E2eReport) -> None:
    test = E2eResult(test_name="export_snapshot")
    t0 = time.perf_counter()
    try:
        result = await client.call_tool("export_snapshot", {"path": "/tmp/e2e-snapshot.ndjson"})
        test.duration_ms = (time.perf_counter() - t0) * 1000
        test.details = {"response": _parse_result(result)}
        test.status = "PASS"
    except Exception as exc:
        test.status = "FAIL"
        test.error = str(exc)
    report.add(test)


async def scan_diff_check(client: McpClient, report: E2eReport) -> None:
    """scan_diff на git-репозитории полигона (все файлы untracked)."""
    test = E2eResult(test_name="scan_diff: git changes")
    t0 = time.perf_counter()
    try:
        result = await client.call_tool("scan_diff", {})
        test.duration_ms = (time.perf_counter() - t0) * 1000
        payload = _parse_result(result)
        total = payload.get("summary", {}).get("total", 0)
        top = payload.get("top_findings", [])
        test.details = {
            "total": total,
            "file_paths": sorted({f.get("file_path") for f in top}),
        }
        if payload.get("error"):
            test.status = "FAIL"
            test.error = f"scan_diff error: {payload['error']}"
        else:
            test.status = "PASS" if total > 0 else "SKIP"
            if total == 0:
                test.error = "no findings in git changes"
    except Exception as exc:
        test.status = "FAIL"
        test.error = str(exc)
    report.add(test)


async def get_fix_context_check(
    client: McpClient, report: E2eReport, finding_ids: list[str]
) -> None:
    """get_fix_context + get_fix_context_batch на реальные finding_id.

    Ответ сервера: get_fix_context → {"status": "ok", "context": ContextPack},
    batch → {"status": "ok", "contexts": [...]} (models/context.py).
    """
    t1 = E2eResult(test_name=f"get_fix_context ({finding_ids[0][:12]}...)")
    t0 = time.perf_counter()
    try:
        result = await client.call_tool("get_fix_context", {"finding_id": finding_ids[0]})
        t1.duration_ms = (time.perf_counter() - t0) * 1000
        payload = _parse_result(result)
        pack = payload.get("context") or {}
        finding = pack.get("finding", {})
        t1.details = {
            "status": payload.get("status"),
            "finding_id": finding.get("fingerprint"),
            "rule_id": finding.get("rule_id"),
            "has_window": pack.get("window") is not None,
            "project_id": pack.get("project", {}).get("project_id"),
        }
        t1.status = "PASS" if (finding.get("fingerprint") or finding.get("finding_id")) else "FAIL"
        if t1.status == "FAIL":
            t1.error = "context pack has no finding"
    except Exception as exc:
        t1.status = "FAIL"
        t1.error = str(exc)
    report.add(t1)

    t2 = E2eResult(test_name="get_fix_context_batch")
    t0 = time.perf_counter()
    try:
        batch = finding_ids[:3]
        result = await client.call_tool("get_fix_context_batch", {"finding_ids": batch})
        t2.duration_ms = (time.perf_counter() - t0) * 1000
        payload = _parse_result(result)
        items = payload.get("contexts") or []
        t2.details = {
            "requested": len(batch),
            "returned": len(items),
            "errors": payload.get("errors", {}),
            "pack_finding_ids": [c.get("finding", {}).get("fingerprint") for c in items],
        }
        t2.status = "PASS" if items else "FAIL"
        if t2.status == "FAIL":
            t2.error = f"batch returned {len(items)} packs for {len(batch)} ids"
    except Exception as exc:
        t2.status = "FAIL"
        t2.error = str(exc)
    report.add(t2)

