"""Прогон сессий: основная E2E-воронка и параллельные сессии."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from e2e_measure.client import McpClient, _parse_result
from e2e_measure.report import E2eReport, E2eResult
from e2e_measure.scenarios.funnel import (
    export_snapshot_check,
    get_fix_context_check,
    get_scan_history_check,
    measure_scan_file,
    measure_scan_project,
    query_findings,
    scan_diff_check,
    submit_feedback,
    suppress_and_rescan,
    verify_fix_not_fixed,
)
from e2e_measure.scenarios.t14 import dedup_stability_recheck


async def run_e2e_session(project_path: str, data_volume: str = "appsecgate-data") -> E2eReport:
    report = E2eReport(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        project_path=project_path,
    )
    async with McpClient(project_path, data_volume=data_volume) as client:
        await measure_scan_project(client, report)
        await scan_diff_check(client, report)
        secrets = await measure_scan_file(client, report, "secrets.py", expected_min=1)
        sqli = await measure_scan_file(client, report, "sql_injection.py", expected_min=1)
        xss = await measure_scan_file(client, report, "xss.py", expected_min=1)
        toml = await measure_scan_file(client, report, "requirements.txt", expected_min=1)
        main_tf = await measure_scan_file(client, report, "main.tf", expected_min=1)
        await query_findings(client, report)

        # T14-6 (B2): повторный скан secrets.py — детерминированный fingerprint (T10).
        await dedup_stability_recheck(client, report)

        # Собираем все доступные finding_id; верхние 3 пойдут в контекст-пакеты.
        finding_ids: list[str] = []
        for payload in (secrets, sqli, xss, toml, main_tf):
            if not payload:
                continue
            for item in payload.get("top_findings", []):
                fid = item.get("finding_id") or item.get("fingerprint")
                if fid and fid not in finding_ids:
                    finding_ids.append(fid)
        finding_id = finding_ids[0] if finding_ids else None

        if finding_ids:
            await get_fix_context_check(client, report, finding_ids)
        else:
            report.add(E2eResult(test_name="get_fix_context", status="SKIP", error="no finding_id"))

        if finding_id:
            await verify_fix_not_fixed(client, report, finding_id)
            await suppress_and_rescan(client, report, finding_id, "secrets.py")
            await submit_feedback(client, report, finding_id)
        else:
            report.add(
                E2eResult(
                    test_name="verify_fix/suppress/feedback", status="SKIP", error="no finding_id"
                )
            )

        await get_scan_history_check(client, report)
        await export_snapshot_check(client, report)
    return report


async def run_parallel_sessions(
    project_path: str,
    other_project_path: str,
    data_volume: str = "appsecgate-data",
) -> E2eReport:
    report = E2eReport(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        project_path=project_path,
    )

    async def _scan(ppath: str, label: str, mount_path: str) -> dict[str, Any]:
        async with McpClient(ppath, mount_path=mount_path, data_volume=data_volume) as client:
            r = await client.call_tool("scan_project", {"path": "."})
            p = _parse_result(r)
            proj = p.get("project", {})
            return {
                "label": label,
                "project_id": proj.get("project_id", "unknown"),
                "project_alias": proj.get("project_alias", "unknown"),
                "total": p.get("summary", {}).get("total", 0),
            }

    test = E2eResult(test_name="parallel sessions: two projects")
    t0 = time.perf_counter()
    try:
        # project_id = sha256(realpath(project_path)) → монтируем проекты в
        # разные пути контейнера, чтобы идентичности не пересеклись.
        results = await asyncio.gather(
            _scan(project_path, "A-vuln", "/workspace"),
            _scan(other_project_path, "B-other", "/workspace-b"),
        )
        test.duration_ms = (time.perf_counter() - t0) * 1000
        test.details = {"sessions": results}
        aid = results[0]["project_id"]
        bid = results[1]["project_id"]
        test.status = "PASS" if aid != bid else "FAIL"
        if test.status == "FAIL":
            test.error = f"project_id collision: {aid} == {bid}"
    except Exception as exc:
        test.status = "FAIL"
        test.error = str(exc)
    report.add(test)
    return report
