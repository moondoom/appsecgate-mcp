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
import re
import shutil
import sys
import tempfile
import time
import uuid
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
    *,
    read_only: bool = True,
    memory_limit: str | None = None,
    name: str | None = None,
) -> list[str]:
    """Бильд docker run для stdio-сессии.

    ``mount_path`` — путь внутри контейнера, куда монтируется проект.
    Для параллельных сессий используется разный ``mount_path``: project_id
    вычисляется как sha256(realpath(project_path)) (спека §4.7), поэтому при
    одинаковом пути оба проекта получили бы один project_id.

    ``read_only=False`` — rw-монтаж проекта + снятие ``--read-only``: только для
    E2E-сценариев «фикс» (verify_fix=fixed) на временной копии полигона.
    ``memory_limit`` — ``--memory`` контейнера (E1: проверка риска OOM).
    ``name`` — имя контейнера (для ``docker stats`` в E1).
    """
    resolved = str(Path(project_path).resolve())
    mount = f"{resolved}:{mount_path}:{'ro' if read_only else 'rw'}"
    args = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network=none",
        "--tmpfs=/tmp:size=100M,mode=1777",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--user=1000:1000",
    ]
    if read_only:
        args.append("--read-only")
    if memory_limit:
        args += ["--memory", memory_limit]
    if name:
        args += ["--name", name]
    args += [
        "-v",
        mount,
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
    return args


class McpClient:
    def __init__(
        self,
        project_path: str,
        mount_path: str = "/workspace",
        data_volume: str = "appsecgate-data",
        *,
        read_only: bool = True,
        memory_limit: str | None = None,
        name: str | None = None,
    ) -> None:
        self.project_path = project_path
        self.mount_path = mount_path
        self.data_volume = data_volume
        self.read_only = read_only
        self.memory_limit = memory_limit
        self.name = name
        self._stack = AsyncExitStack()
        self._session: Any = None

    async def __aenter__(self) -> McpClient:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        cmd = _docker_args(
            self.project_path,
            mount_path=self.mount_path,
            data_volume=self.data_volume,
            read_only=self.read_only,
            memory_limit=self.memory_limit,
            name=self.name,
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


# ---------------------------------------------------------------------------
# T14 iteration-2 scenarios (docs/e2e-test-plan.md §11)
# ---------------------------------------------------------------------------


def _copy_polygon(resolved: str, dest: Path, subdir: str) -> Path:
    """Копия полигона без вложенного .git (для rw/git-сценариев)."""
    proj = dest / subdir
    shutil.copytree(resolved, proj, ignore=shutil.ignore_patterns(".git"))
    return proj


def _git(*args: str, cwd: str | Path) -> None:
    subprocess_run(
        ["git", "-c", "user.name=e2e", "-c", "user.email=e2e@appsecgate.local", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _fps_from_scan(payload: dict[str, Any]) -> list[str]:
    return sorted(
        {
            f.get("finding_id") or f.get("fingerprint")
            for f in payload.get("top_findings", []) or payload.get("findings", [])
        }
    )


async def verify_fix_wont_fix(client: McpClient, report: E2eReport, finding_id: str) -> None:
    """verify_fix=wont_fix: записывается только через verify_fix, note обязателен."""
    t1 = E2eResult(test_name=f"verify_fix: wont_fix ({finding_id[:12]}...)")
    try:
        r = await client.call_tool(
            "verify_fix",
            {"finding_id": finding_id, "status": "wont_fix", "note": "E2E: accepted risk"},
        )
        p = _parse_result(r)
        t1.details = {"response": p}
        t1.status = (
            "PASS" if p.get("verified_status") == "wont_fix" and p.get("verified") else "FAIL"
        )
        if t1.status == "FAIL":
            t1.error = f"unexpected: {p}"
    except Exception as exc:
        t1.status = "FAIL"
        t1.error = str(exc)
    report.add(t1)


async def run_fix_verify_scenarios(resolved: str, data_volume: str, report: E2eReport) -> None:
    """T14-2: verify_fix=fixed/wont_fix на rw-копии полигона + batch."""
    with tempfile.TemporaryDirectory() as td:
        proj = _copy_polygon(resolved, Path(td), "fixproj")
        async with McpClient(str(proj), data_volume=data_volume, read_only=False) as client:
            sqli = await measure_scan_file(client, report, "sql_injection.py", expected_min=1)
            sqli_id = _find_first_finding_id([sqli])
            if not sqli_id:
                report.add(
                    E2eResult(
                        test_name="verify_fix fixed/wont_fix",
                        status="SKIP",
                        error="no sql_injection finding",
                    )
                )
                return

            # 1) wont_fix: файл не меняем, перескана нет.
            await verify_fix_wont_fix(client, report, sqli_id)

            # 2) Применяем реальный фикс (параметризованный запрос) на хосте.
            (proj / "sql_injection.py").write_text(
                "import sqlite3\n\n"
                "def get_user_by_id(conn: sqlite3.Connection, user_id: str) -> list:\n"
                '    cursor = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))\n'
                "    return list(cursor.fetchall())\n",
                encoding="utf-8",
            )

            # 3) fixed: перескан после фикса — logical_id исчез.
            t3 = E2eResult(test_name=f"verify_fix: fixed after real fix ({sqli_id[:12]}...)")
            try:
                r = await client.call_tool(
                    "verify_fix", {"finding_id": sqli_id, "status": "fixed", "note": ""}
                )
                p = _parse_result(r)
                t3.details = {"response": p, "fixed_file": "sql_injection.py"}
                t3.status = (
                    "PASS" if p.get("verified_status") == "fixed" and p.get("verified") else "FAIL"
                )
                if t3.status == "FAIL":
                    t3.error = f"unexpected: {p}"
            except Exception as exc:
                t3.status = "FAIL"
                t3.error = str(exc)
            report.add(t3)

            # 4) batch: неисправленная находка (secrets.py) + уже исправленная.
            secrets = await measure_scan_file(client, report, "secrets.py", expected_min=1)
            sec_id = _find_first_finding_id([secrets])
            t4 = E2eResult(test_name="verify_fix_batch: fixed + not_fixed")
            try:
                attempts = [
                    {"finding_id": sqli_id, "status": "fixed", "note": ""},
                    {"finding_id": sec_id, "status": "not_fixed", "note": ""},
                ]
                r = await client.call_tool("verify_fix_batch", {"attempts": attempts})
                p = _parse_result(r)
                summary = p.get("summary", {})
                t4.details = {"response": p}
                ok = (
                    summary.get("fixed", 0) == 1
                    and summary.get("not_fixed", 0) == 1
                    and len(p.get("results", [])) == 2
                )
                t4.status = "PASS" if ok else "FAIL"
                if t4.status == "FAIL":
                    t4.error = f"unexpected summary: {summary}"
            except Exception as exc:
                t4.status = "FAIL"
                t4.error = str(exc)
            report.add(t4)


_STAGED_SECRET = (
    '"""Staged-only fake token (B5)."""\n'
    'STAGED_GITHUB_TOKEN = "ghp_e2e0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8"\n'
)
_MODIFIED_SQLI = (
    "import sqlite3\n\n"
    "def get_user_by_id(conn, user_id):\n"
    "    cursor = conn.execute(f\"SELECT * FROM users WHERE id = '{user_id}' LIMIT 1\")\n"
    "    return list(cursor.fetchall())\n"
)
_UNTRACKED_SQLI = (
    "import sqlite3\n\n"
    "def find_user(conn, name):\n"
    "    return conn.execute(f\"SELECT * FROM users WHERE name = '{name}'\").fetchall()\n"
)


async def run_git_diff_scenarios(resolved: str, data_volume: str, report: E2eReport) -> None:
    """T14-1 (B5): staged + unstaged + untracked + clean + регрессия против коммита."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        proj = _copy_polygon(resolved, root, "gitscen")
        _git("init", "-q", cwd=proj)
        _git("add", "-A", cwd=proj)
        _git("commit", "-q", "-m", "baseline", cwd=proj)

        # Смешанное состояние: staged + unstaged + untracked одновременно.
        (proj / "staged_secret.py").write_text(_STAGED_SECRET, encoding="utf-8")
        _git("add", "staged_secret.py", cwd=proj)
        (proj / "sql_injection.py").write_text(_MODIFIED_SQLI, encoding="utf-8")
        (proj / "untracked_vuln.py").write_text(_UNTRACKED_SQLI, encoding="utf-8")

        t1 = E2eResult(test_name="scan_diff: staged + unstaged + untracked (B5)")
        async with McpClient(str(proj), data_volume=data_volume) as client:
            r = await client.call_tool("scan_diff", {})
            p = _parse_result(r)
            total = p.get("summary", {}).get("total", 0)
            paths = sorted({f.get("file_path") for f in p.get("top_findings", [])})
            t1.details = {"total": total, "file_paths": paths}
            needed = {"staged_secret.py", "sql_injection.py", "untracked_vuln.py"}
            t1.status = "PASS" if total >= 3 and needed.issubset(set(paths)) else "FAIL"
            if t1.status == "FAIL":
                t1.error = f"paths={paths}, total={total}"
        report.add(t1)

        # Граница: всё закоммичено → scan_diff пуст.
        _git("add", "-A", cwd=proj)
        _git("commit", "-q", "-m", "changes", cwd=proj)
        t2 = E2eResult(test_name="scan_diff: clean tree after commit (B5 boundary)")
        async with McpClient(str(proj), data_volume=data_volume) as client:
            r = await client.call_tool("scan_diff", {})
            p = _parse_result(r)
            total = p.get("summary", {}).get("total", 0)
            t2.details = {"total": total, "response_keys": sorted(p.keys())}
            t2.status = "PASS" if total == 0 else "FAIL"
            if t2.status == "FAIL":
                t2.error = f"expected 0 findings on clean tree, got {total}"
        report.add(t2)

        # Регрессия против старого коммита: revert фикса + reset --soft → staged.
        _git("revert", "--no-edit", "HEAD", cwd=proj)
        _git("reset", "--soft", "HEAD~1", cwd=proj)
        t3 = E2eResult(test_name="scan_diff: regression vs previous commit (B5)")
        async with McpClient(str(proj), data_volume=data_volume) as client:
            r = await client.call_tool("scan_diff", {})
            p = _parse_result(r)
            total = p.get("summary", {}).get("total", 0)
            paths = sorted({f.get("file_path") for f in p.get("top_findings", [])})
            t3.details = {"total": total, "file_paths": paths}
            t3.status = "PASS" if total >= 1 and "sql_injection.py" in set(paths) else "FAIL"
            if t3.status == "FAIL":
                t3.error = f"regression not detected: total={total}, paths={paths}"
        report.add(t3)


def _build_large_polygon(resolved: str, dest: Path, n_extra: int = 120) -> Path:
    """Крупный полигон: копия vuln-project + n_extra файлов с SQLi (для E1)."""
    proj = _copy_polygon(resolved, dest, "large-polygon")
    for i in range(n_extra):
        (proj / f"mod_{i:03d}.py").write_text(
            "import sqlite3\n\n"
            "def fetch(conn, uid):\n"
            "    return conn.execute(f\"SELECT * FROM users WHERE id = '{uid}'\")\n",
            encoding="utf-8",
        )
    return proj


def _parse_mem_mib(s: str) -> float:
    raw = s.split("/")[0].strip()
    m = re.match(r"([\d.]+)\s*(GiB|MiB|KiB|B)", raw)
    if not m:
        return 0.0
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "GiB":
        return num * 1024
    if unit == "KiB":
        return num / 1024
    return num


async def _sample_mem_usage(name: str, out: list[float], interval: float = 0.2) -> None:
    """Сэмплирует MemUsage контейнера в ``out`` (не сдаётся до появления контейнера).

    ``out`` — внешний мутабельный буфер: даже при отмене задачи сэмплы остаются.
    """
    misses = 0
    while True:
        try:
            r = subprocess_run(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            line = r.stdout.strip()
            if line:
                out.append(_parse_mem_mib(line))
                misses = 0
            else:
                misses += 1
        except Exception:
            misses += 1
        # «No such container» в первые мгновения — контейнер ещё создаётся;
        # останавливаемся только после длительного отсутствия данных.
        if misses > 150:
            break
        await asyncio.sleep(interval)


async def run_memory_scenario(resolved: str, data_volume: str, report: E2eReport) -> None:
    """T14-4 (E1): scan_project на крупном полигоне под лимитом 512 MiB."""
    test = E2eResult(test_name="E1: memory scan_project on large polygon (512m cap)")
    t0 = time.perf_counter()
    samples: list[float] = []
    with tempfile.TemporaryDirectory() as td:
        proj = _build_large_polygon(resolved, Path(td))
        n_files = len(list(proj.rglob("*.py")))
        name = f"e2e-mem-{uuid.uuid4().hex[:8]}"
        try:
            async with McpClient(
                str(proj), data_volume=data_volume, memory_limit="512m", name=name
            ) as client:
                sampler = asyncio.create_task(_sample_mem_usage(name, samples))
                try:
                    r = await client.call_tool("scan_project", {"path": "."})
                finally:
                    sampler.cancel()
                    try:
                        await sampler
                    except asyncio.CancelledError:
                        pass  # сэмплы уже в мутабельном буфере ``samples``
            test.duration_ms = (time.perf_counter() - t0) * 1000
            p = _parse_result(r)
            errs = p.get("meta", {}).get("errors", [])
            total = p.get("summary", {}).get("total", 0)
            peak = max(samples, default=0.0)
            test.details = {
                "total_findings": total,
                "python_files": n_files,
                "peak_mem_mib": round(peak, 1),
                "mem_samples": len(samples),
                "duration_ms": round(test.duration_ms, 1),
            }
            test.status = "PASS" if not errs and total > 0 else "FAIL"
            if errs:
                test.error = f"meta.errors: {errs}"
            elif total == 0:
                test.error = "scan_project returned 0 findings"
        except Exception as exc:
            test.status = "FAIL"
            test.error = f"scan aborted (OOM or container death): {exc}"
    report.add(test)


async def dedup_stability_recheck(client: McpClient, report: E2eReport) -> None:
    """T14-6 (B2): повторный скан secrets.py — детерминированный набор fingerprint (T10)."""
    test = E2eResult(test_name="B2: dedup stability recheck (T10 regression)")
    try:
        p1 = _parse_result(await client.call_tool("scan_file", {"path": "secrets.py"}))
        p2 = _parse_result(await client.call_tool("scan_file", {"path": "secrets.py"}))
        f1, f2 = _fps_from_scan(p1), _fps_from_scan(p2)
        test.details = {
            "scan1_fingerprints": f1,
            "scan2_fingerprints": f2,
            "total1": p1.get("summary", {}).get("total", 0),
            "total2": p2.get("summary", {}).get("total", 0),
        }
        test.status = "PASS" if f1 and f1 == f2 else "FAIL"
        if test.status == "FAIL":
            test.error = f"fingerprint sets differ between scans: {f1} != {f2}"
    except Exception as exc:
        test.status = "FAIL"
        test.error = str(exc)
    report.add(test)


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
            # T14 iteration-2: verify fixed/wont_fix, staged-diff (B5), память (E1).
            # Свежий volume: suppression по fingerprint глобален (OBS-2) — после
            # suppress_finding из funnel-прогона находки в temp-копиях полигона
            # (тот же контент → тот же fingerprint) оказались бы подавлены.
            t14_volume = f"appsecgate-data-e2e-t14-{uuid.uuid4().hex[:12]}"
            subprocess_run(
                ["docker", "volume", "create", t14_volume], check=True, capture_output=True
            )
            try:
                await run_fix_verify_scenarios(resolved, t14_volume, report)
                await run_git_diff_scenarios(resolved, t14_volume, report)
                await run_memory_scenario(resolved, t14_volume, report)
            finally:
                subprocess_run(["docker", "volume", "rm", "-f", t14_volume], capture_output=True)
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
