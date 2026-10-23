#!/usr/bin/env python3
"""Script for E2E testing of AppSecGate MCP server (docs/e2e-test-plan.md).

Runs the full scan -> context -> fix -> verify funnel against a live
Docker container. Reports results as JSON.

Usage:
    python3 scripts/e2e_measure.py \\
        --project-path /abs/path/to/vuln-project \\
        --other-project-path /abs/path/to/other-project \\
        --output e2e-results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import run as subprocess_run
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("e2e_measure")

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class E2eResult:
    test_name: str
    status: str = "PASS"  # PASS | FAIL | SKIP
    duration_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class E2eReport:
    timestamp: str = ""
    project_path: str = ""
    results: list[E2eResult] = field(default_factory=list)

    def add(self, result: E2eResult) -> None:
        self.results.append(result)
        icon = "✅" if result.status == "PASS" else ("❌" if result.status == "FAIL" else "⏭️")
        logger.info("%s %s (%s ms)", icon, result.test_name, round(result.duration_ms, 1))
        if result.error:
            logger.warning("  ⚠️  %s", result.error)

    def summary(self) -> dict[str, Any]:
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        skipped = sum(1 for r in self.results if r.status == "SKIP")
        return {
            "total": len(self.results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "success_rate": f"{passed / max(len(self.results), 1) * 100:.1f}%",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "project_path": self.project_path,
            "summary": self.summary(),
            "results": [
                {
                    "test": r.test_name,
                    "status": r.status,
                    "duration_ms": round(r.duration_ms, 1),
                    "error": r.error,
                    "details": r.details,
                }
                for r in self.results
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "content") and result.content:
        for part in result.content:
            if hasattr(part, "text") and part.text:
                try:
                    return json.loads(part.text)
                except json.JSONDecodeError:
                    return {"raw_text": part.text}
        return {"raw": str(result.content)}
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    return {"raw": str(result)}


def _find_first_finding_id(results: list[dict[str, Any] | None]) -> str | None:
    for r in results:
        if r is None:
            continue
        # scan_file возвращает announce-формат: детали в top_findings.
        for key in ("top_findings", "findings"):
            for item in r.get(key, []):
                fid = item.get("finding_id") or item.get("fingerprint")
                if fid:
                    return fid
    return None


# ---------------------------------------------------------------------------
# Docker MCP client
# ---------------------------------------------------------------------------


def _docker_args(
    project_path: str,
    image: str = "moondoom/appsecgate-mcp:0.1.0",
    cache_volume: str = "appsecgate-cache",
    data_volume: str = "appsecgate-data",
    mount_path: str = "/workspace",
) -> list[str]:
    """Бильд docker run для stdio-сессии.

    ``mount_path`` — путь внутри контейнера, куда монтируется проект.
    Для параллельных сессий используется разный ``mount_path``: project_id
    вычисляется как sha256(realpath(project_path)) (спека §4.7), поэтому при
    одинаковом пути оба проекта получили бы один project_id.
    """
    resolved = str(Path(project_path).resolve())
    return [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network=none",
        "--read-only",
        "--tmpfs=/tmp:size=100M,mode=1777",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--user=1000:1000",
        "-v",
        f"{resolved}:{mount_path}:ro",
        "-v",
        f"{resolved}/.appsecgate-mcp:/.appsecgate-mcp:ro",
        "-v",
        f"{cache_volume}:/home/appsecgate/.cache",
        "-v",
        f"{data_volume}:/home/appsecgate/.appsecgate-mcp",
        "-e",
        f"APPSECGATE_PROJECT_PATH={mount_path}",
        "-e",
        "HOME=/home/appsecgate",
        image,
        "--transport",
        "stdio",
    ]


class McpClient:
    def __init__(
        self,
        project_path: str,
        mount_path: str = "/workspace",
        data_volume: str = "appsecgate-data",
    ) -> None:
        self.project_path = project_path
        self.mount_path = mount_path
        self.data_volume = data_volume
        self._stack = AsyncExitStack()
        self._session: Any = None

    async def __aenter__(self) -> McpClient:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        cmd = _docker_args(
            self.project_path, mount_path=self.mount_path, data_volume=self.data_volume
        )
        sp = StdioServerParameters(command=cmd[0], args=cmd[1:])
        self._read, self._write = await self._stack.enter_async_context(stdio_client(sp))
        self._session = await self._stack.enter_async_context(
            ClientSession(self._read, self._write)
        )
        await self._session.initialize()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._stack.aclose()

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return await self._session.call_tool(name, arguments or {})


# ---------------------------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------------------------


async def measure_scan_project(client: McpClient, report: E2eReport) -> None:
    test = E2eResult(test_name="NF: scan_project duration")
    t0 = time.perf_counter()
    try:
        result = await client.call_tool("scan_project", {"path": "."})
        dt = (time.perf_counter() - t0) * 1000
        test.duration_ms = dt
        payload = _parse_result(result)
        s = payload.get("summary", {})
        m = payload.get("meta", {})
        errs = m.get("errors", [])
        test.details = {
            "total_findings": s.get("total", -1),
            "meta_errors": errs,
            "meta_warnings": m.get("warnings", []),
            "duration_ms_raw": dt,
            "scan_mode": m.get("mode", "unknown"),
            "by_severity": s.get("by_severity", {}),
            "by_category": s.get("by_category", {}),
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
            payload.get("isError")
            or payload.get("error")
            or payload.get("status") == "error"
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


# ---------------------------------------------------------------------------
# Session runners
# ---------------------------------------------------------------------------


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
        await query_findings(client, report)

        # Собираем все доступные finding_id; верхние 3 пойдут в контекст-пакеты.
        finding_ids: list[str] = []
        for payload in (secrets, sqli, xss, toml):
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


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="AppSecGate MCP E2E test runner")
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--other-project-path", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--skip-parallel", action="store_true")
    args = parser.parse_args()

    resolved = str(Path(args.project_path).resolve())
    if not Path(resolved).is_dir():
        sys.exit(f"Error: directory not found: {resolved}")

    other_resolved = None
    if args.other_project_path:
        other_resolved = str(Path(args.other_project_path).resolve())
        if not Path(other_resolved).is_dir():
            sys.exit(f"Error: other-project directory not found: {other_resolved}")

    async def run_all() -> dict[str, Any]:
        report = E2eReport(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            project_path=resolved,
        )
        # Свежий data volume на каждый прогон: shown_findings.db/suppressions живут
        # там, и без изоляции suppression по fingerprint (SuppressionStore, PK без
        # project_id) переживает прогоны и искажает следующие. Кэш-волум (контентно-
        # адресуемый) шарим — это безопасно.
        import uuid

        data_volume = f"appsecgate-data-e2e-{uuid.uuid4().hex[:12]}"
        try:
            subprocess_run(
                ["docker", "volume", "create", data_volume], check=True, capture_output=True
            )
        except Exception as exc:
            logger.error("Failed to create data volume %s: %s", data_volume, exc)
            raise

        try:
            # Параллельные сессии запускаем ДО основного прогона: вызванное в нём
            # suppress_finding хранится по fingerprint БЕЗ project_id (SuppressionStore),
            # т.е. глобально. Если бы параллельный скан шёл после, находка с тем же
            # fingerprint в other-project была бы подавлена — ложное «0 находок».
            if other_resolved and not args.skip_parallel:
                logger.info("=" * 60)
                logger.info("E2E: parallel sessions (before mutations)")
                logger.info("=" * 60)
                pr = await run_parallel_sessions(resolved, other_resolved, data_volume)
                report.results.extend(pr.results)
            logger.info("=" * 60)
            logger.info("E2E: running for %s", resolved)
            logger.info("=" * 60)
            funnel = await run_e2e_session(resolved, data_volume)
            report.results.extend(funnel.results)
        finally:
            subprocess_run(
                ["docker", "volume", "rm", "-f", data_volume],
                capture_output=True,
            )
        logger.info("")
        logger.info("=" * 60)
        logger.info("SUMMARY: %s", report.summary())
        logger.info("=" * 60)
        return report.to_dict()

    result = asyncio.run(run_all())
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        logger.info("Report saved: %s", out_path)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
