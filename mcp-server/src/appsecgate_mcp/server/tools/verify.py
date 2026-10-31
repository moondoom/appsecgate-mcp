"""Тулы верификации фиксов: verify_fix, verify_fix_batch + помощники."""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.models.finding import Finding
from appsecgate_mcp.server.app import mcp
from appsecgate_mcp.server.logging_utils import _log_tool
from appsecgate_mcp.server.session import SessionState, _resolve_inside_project
from appsecgate_mcp.server.tools.common import _BATCH_LIMIT, ensure_session


async def _read_source(state: SessionState, file_path: str) -> str:
    """Читает исходник файла внутри корня проекта (зеркалит логику coordinator)."""
    try:
        target = _resolve_inside_project(file_path, state.project_path)
        return target.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


async def _verification_scan(state: SessionState, file_path: str) -> list[tuple[Finding, str]]:
    """Пересканирует файл (persist=False) и возвращает пары (finding, logical_id)."""
    result = await state.coordinator.scan([file_path], mode="file", persist=False)
    pairs: list[tuple[Finding, str]] = []
    for finding in result.findings:
        source = await _read_source(state, finding.file_path)
        # Отложенный доступ: тесты патчат server.compute_logical_id.
        import appsecgate_mcp.server as server_mod

        logical_id = server_mod.compute_logical_id(
            finding.rule_id, finding.file_path, finding.line_start, source
        )
        pairs.append((finding, logical_id))
    return pairs


def _resolve_attempt_target(row: dict[str, Any]) -> dict[str, Any]:
    """Достаёт идентификаторы ``(fingerprint, logical_id, rule_id, file_path)``."""
    return {
        "fingerprint": row["fingerprint"],
        "logical_id": row.get("logical_id"),
        "rule_id": row["rule_id"],
        "file_path": row["file_path"],
    }


async def _verify_attempts(
    state: SessionState, attempts: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    """Проверяет батч попыток: перескан каждого файла один раз + запись fix_attempts.

    Возвращает ``(results, summary, file_rescans)``. ``file_rescans``: file_path → число
    появлений в батче (счётчик, а не scan_id — серверные сканы не имеют ID).
    """
    resolved: list[dict[str, Any]] = []
    for attempt in attempts:
        row = await state.shown_store.find(attempt["finding_id"])
        if row is None:
            resolved.append({**attempt, "_error": f"finding not found: {attempt['finding_id']}"})
            continue
        target = _resolve_attempt_target(row)
        if target["logical_id"] is None:
            resolved.append(
                {**attempt, "_error": f"no logical_id for finding: {attempt['finding_id']}"}
            )
            continue
        resolved.append({**attempt, "_target": target})

    scan_cache: dict[str, list[tuple[Finding, str]]] = {}
    results: list[dict[str, Any]] = []
    for attempt in resolved:
        if "_error" in attempt:
            results.append(
                {
                    "logical_id": "",
                    "fingerprint": attempt["finding_id"],
                    "reported_status": attempt["status"],
                    "verified_status": "error",
                    "verified": False,
                    "reason": attempt["_error"],
                }
            )
            continue

        target = attempt["_target"]
        reported = attempt["status"]
        note = attempt.get("note") or ""
        logical_id = target["logical_id"]

        if reported == "wont_fix":
            new_fingerprints: list[str] = []
            verified_status = "wont_fix"
        else:
            scan_pairs = scan_cache.get(target["file_path"])
            if scan_pairs is None:
                scan_pairs = await _verification_scan(state, target["file_path"])
                scan_cache[target["file_path"]] = scan_pairs
            new_fingerprints = [f.fingerprint for f, lid in scan_pairs if lid == logical_id]
            verified_status = "not_fixed" if new_fingerprints else "fixed"

        await state.fix_attempts_store.record(
            project_id=state.project_id,
            logical_id=logical_id,
            fingerprint=target["fingerprint"],
            rule_id=target["rule_id"],
            file_path=target["file_path"],
            reported_status=reported.upper(),
            verified_status=verified_status.upper(),
            note=note,
            session_id=state.session_id,
        )
        if verified_status == "wont_fix":
            await state.shown_store.set_status(
                target["fingerprint"],
                "WONT_FIX",
                reason=note,
            )
        elif reported == "fixed" and verified_status == "fixed":
            # §2.9: явное подтверждение фикса — единственный путь в FIXED (§2.3).
            await state.shown_store.set_status(
                target["fingerprint"],
                "FIXED",
                confirmed_by="verify_fix",
            )
        elif reported == "fixed" and verified_status == "not_fixed":
            # §2.9: заявили fixed, перескан нашёл — регрессия/ложное подтверждение.
            await state.shown_store.set_status(target["fingerprint"], "REOPENED")
        # reported == "not_fixed" → статус не меняется (§2.9).

        results.append(
            {
                "logical_id": logical_id,
                "fingerprint": target["fingerprint"],
                "reported_status": reported,
                "verified_status": verified_status,
                "verified": reported == verified_status,
                "new_fingerprints": new_fingerprints,
                "reason": "",
            }
        )

    summary: dict[str, int] = {}
    for result in results:
        key = result["verified_status"]
        summary[key] = summary.get(key, 0) + 1
    file_rescans = {path: 1 for path in scan_cache}
    return results, summary, file_rescans


@mcp.tool()
@_log_tool
async def verify_fix(finding_id: str, status: str, note: str = "") -> dict[str, Any]:
    """Verify a single finding: rescan the file and match by (logical_id).

    status: fixed | not_fixed | wont_fix. ``wont_fix`` requires a note.

    Response contract (T12) — agents MUST read ``verified_status``, not ``status``:
      - ``status``           — transport status of the operation: "ok" | "error".
      - ``verified_status``  — canonical verification result:
        fixed | not_fixed | wont_fix.
      - ``verified``         — bool: whether ``reported_status`` agrees with the
        rescan. ``verified=true`` with ``not_fixed`` means "finding is still
        present and the agent's claim was confirmed" — NOT "fix verified".
      - ``new_fingerprints`` — fingerprints still matching the same ``logical_id``
        after the rescan (empty when fixed or wont_fix).
    """
    state = await ensure_session()
    if state.fix_attempts_store is None or state.shown_store is None:
        return {"status": "error", "reason": "session not initialized"}
    normalized = status.strip().lower()
    if normalized not in ("fixed", "not_fixed", "wont_fix"):
        return {
            "status": "error",
            "reason": f"invalid status '{status}': expected fixed|not_fixed|wont_fix",
        }
    if normalized == "wont_fix" and not note.strip():
        return {"status": "error", "reason": "wont_fix requires a note"}
    results, _summary, _file_rescans = await _verify_attempts(
        state, [{"finding_id": finding_id, "status": normalized, "note": note}]
    )
    result = results[0]
    if result.get("verified_status") == "error":
        return {"status": "error", "reason": result["reason"]}
    return {"status": "ok", **result}


@mcp.tool()
@_log_tool
async def verify_fix_batch(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify up to 20 findings; each file is rescanned once.

    attempts: [{"finding_id": str, "status": fixed|not_fixed|wont_fix, "note": str}].

    Response contract (T12) — agents MUST read per-attempt ``verified_status``,
    not the top-level ``status``:
      - ``status``  — transport status of the operation: "ok" | "error".
      - ``results`` — per-attempt outcomes; each item carries ``verified_status``
        (fixed | not_fixed | wont_fix) and ``verified`` (reported == rescan).
      - ``summary`` — counts of outcomes keyed by ``verified_status``.
    """
    state = await ensure_session()
    if state.fix_attempts_store is None or state.shown_store is None:
        return {"status": "error", "reason": "session not initialized"}
    if len(attempts) > _BATCH_LIMIT:
        return {
            "status": "error",
            "reason": f"batch limit exceeded: max {_BATCH_LIMIT} attempts",
            "limit": _BATCH_LIMIT,
        }
    normalized: list[dict[str, Any]] = []
    for attempt in attempts:
        finding_id = attempt.get("finding_id")
        status = str(attempt.get("status", "")).strip().lower()
        if not finding_id:
            return {"status": "error", "reason": "attempt missing 'finding_id'"}
        if status not in ("fixed", "not_fixed", "wont_fix"):
            return {"status": "error", "reason": f"invalid status '{status}' for {finding_id}"}
        note = str(attempt.get("note", "") or "")
        if status == "wont_fix" and not note.strip():
            return {"status": "error", "reason": f"wont_fix requires a note: {finding_id}"}
        normalized.append({"finding_id": finding_id, "status": status, "note": note})
    results, summary, file_rescans = await _verify_attempts(state, normalized)
    return {
        "status": "ok",
        "results": results,
        "file_rescans": file_rescans,
        "summary": summary,
    }
