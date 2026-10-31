"""T14 (третья итерация, PR-E): сценарии reconciliation scan_project (ADR-0005 §3.4).

- scan_project() дважды без изменений → всё SHOWN (counts.reaffirmed), new=0.
- правка файла → scan_project() → POTENTIALLY_FIXED + requires_confirmation.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from e2e_measure.client import McpClient, _counts_total, _parse_result
from e2e_measure.report import E2eReport, E2eResult

_SQLI_FIXED = (
    "import sqlite3\n\n"
    "def get_user_by_id(conn: sqlite3.Connection, user_id: str) -> list:\n"
    '    cursor = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))\n'
    "    return list(cursor.fetchall())\n"
)


def _copy_polygon(resolved: str, dest: Path, subdir: str) -> Path:
    """Копия полигона без вложенного .git (для rw-сценариев)."""
    proj = dest / subdir
    shutil.copytree(resolved, proj, ignore=shutil.ignore_patterns(".git"))
    return proj


async def _scan_and_statuses(
    client: McpClient,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """scan_project() + GROUP BY status по v_findings (для §3.4-проверок)."""
    payload = _parse_result(await client.call_tool("scan_project", {}))
    q = _parse_result(
        await client.call_tool(
            "query_findings_db",
            {"sql": "SELECT status, COUNT(*) AS n FROM v_findings GROUP BY status"},
        )
    )
    return payload, q.get("rows", [])


async def run_reconcile_repeat(client: McpClient, report: E2eReport) -> None:
    """§3.4: scan_project() дважды без изменений → всё SHOWN (reaffirmed), new=0."""
    test = E2eResult(test_name="T14-7: scan_project repeat → all SHOWN (reaffirmed)")
    try:
        p1 = _parse_result(await client.call_tool("scan_project", {}))
        p2, status_rows = await _scan_and_statuses(client)
        c1, c2 = p1.get("counts", {}), p2.get("counts", {})
        total2 = _counts_total(p2)
        test.details = {
            "first_counts": c1,
            "second_counts": c2,
            "total_second": total2,
            "v_findings_statuses": status_rows,
        }
        ok = (
            c1.get("new", 0) > 0
            and c2.get("new", 0) == 0
            and c2.get("reaffirmed", 0) >= c1.get("new", 0)
            and total2 > 0
            and bool(status_rows)
            and all(row.get("status") == "SHOWN" for row in status_rows)
        )
        test.status = "PASS" if ok else "FAIL"
        if not ok:
            test.error = f"unexpected reconcile: {c1} → {c2}, statuses={status_rows}"
    except Exception as exc:
        test.status = "FAIL"
        test.error = str(exc)
    report.add(test)


async def run_reconcile_edit(resolved: str, data_volume: str, report: E2eReport) -> None:
    """§3.4: правка файла → scan_project() → POTENTIALLY_FIXED + requires_confirmation."""
    test = E2eResult(test_name="T14-8: edit file → POTENTIALLY_FIXED (requires_confirmation)")
    with tempfile.TemporaryDirectory() as td:
        proj = _copy_polygon(resolved, Path(td), "recproj")
        try:
            async with McpClient(str(proj), data_volume=data_volume, read_only=False) as client:
                p1 = _parse_result(await client.call_tool("scan_project", {}))
                (proj / "sql_injection.py").write_text(_SQLI_FIXED, encoding="utf-8")
                p2 = _parse_result(await client.call_tool("scan_project", {}))
                counts = p2.get("counts", {})
                rc = p2.get("requires_confirmation", {})
                test.details = {
                    "before_counts": p1.get("counts", {}),
                    "after_counts": counts,
                    "requires_confirmation": rc,
                    "suggested_action": p2.get("suggested_action"),
                }
                ok = (
                    counts.get("potentially_fixed", 0) >= 1
                    and bool(rc.get("finding_ids"))
                    and rc.get("total_potentially_fixed", 0) >= 1
                    and str(p2.get("suggested_action", "")).startswith("run verify_fix_batch")
                )
                test.status = "PASS" if ok else "FAIL"
                if not ok:
                    test.error = f"unexpected reconcile: counts={counts}, rc={rc}"
        except Exception as exc:
            test.status = "FAIL"
            test.error = str(exc)
    report.add(test)


async def run_reconcile_scenarios(resolved: str, data_volume: str, report: E2eReport) -> None:
    """T14, третья итерация (PR-E): повторный scan_project + edit → POTENTIALLY_FIXED."""
    with tempfile.TemporaryDirectory() as td:
        proj = _copy_polygon(resolved, Path(td), "recproj")
        async with McpClient(str(proj), data_volume=data_volume) as client:
            await run_reconcile_repeat(client, report)
    await run_reconcile_edit(resolved, data_volume, report)
