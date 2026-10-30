"""Сценарии T14 (вторая итерация E2E): fix-verify, git-diff, память, дедуп."""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from subprocess import run as subprocess_run
from typing import Any

from e2e_measure.client import McpClient, _find_first_finding_id, _parse_result
from e2e_measure.report import E2eReport, E2eResult
from e2e_measure.scenarios.funnel import measure_scan_file


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
    '    cursor = conn.execute(f"SELECT * FROM users WHERE id = \'{user_id}\' LIMIT 1")\n'
    "    return list(cursor.fetchall())\n"
)
_UNTRACKED_SQLI = (
    "import sqlite3\n\n"
    "def find_user(conn, name):\n"
    '    return conn.execute(f"SELECT * FROM users WHERE name = \'{name}\'").fetchall()\n'
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
