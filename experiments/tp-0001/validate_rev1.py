#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROJECTS = ("structlog", "aitextgen")
PREFIX = os.environ.get("REV1_RUN_PREFIX", "rev1")
OUTPUT = ROOT / "artifacts" / f"{PREFIX}-validation.json"
_NAMESPACE = uuid.UUID("b0a528a4-9e2f-4f24-a8f0-f864b18466a1")


def _label(phase: str) -> str:
    return f"{PREFIX}-{phase}"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _report(label: str, project: str) -> dict[str, Any]:
    return _load(ROOT / "artifacts" / f"{label}-gemmaq3-p1-{project}" / "report.json")


def _events(label: str, project: str) -> list[dict[str, Any]]:
    path = ROOT / "runtime" / f"data-{label}-gemmaq3-p1-{project}" / "triage_verdicts.ndjson"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _project_key(project: str) -> str:
    return f"{project}-tp0001-agent300-gemmaq3-p1-{project}"


def _master_request(path: str, project: str, *, payload: dict[str, Any] | None = None) -> Any:
    config = _load(ROOT / "artifacts" / "agent300-run-config.json")
    keys = _load(ROOT / "runtime" / "agent300-keys.json")
    key = _project_key(project)
    url = f"{config['master']['host_url']}{path}"
    data = None
    headers = {"Authorization": f"Bearer {keys[key]}"}
    if "?" in path:
        url += f"&project={key}"
    else:
        url += f"?project={key}"
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _audit_verdict_count(project: str) -> int:
    result = _master_request("/v1/audit", project)
    return sum(
        row.get("event_type") == "triage_verdicted" and row.get("outcome") == "accepted"
        for row in result["audit"]
    )


def _run(label: str, projects: tuple[str, ...], ttl: str) -> dict[str, dict[str, Any]]:
    subprocess.run(
        [
            "python3",
            "run_agent300.py",
            "--label",
            label,
            "--identity-label",
            "agent300",
            "--projects",
            ",".join(projects),
            "--reuse-ttl",
            ttl,
            "--knowledge-cutoff",
            "",
        ],
        cwd=ROOT,
        check=True,
    )
    return {project: _report(label, project) for project in projects}


def _signature(report: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {
        item["finding_id"]: (item["verdict"], item.get("confidence_level"))
        for item in report.get("verdicts", [])
    }


def _coverage_errors(report: dict[str, Any]) -> list[str]:
    unique_ids = {item["finding_id"] for item in report.get("findings", [])}
    verdict_ids = set(_signature(report))
    errors = []
    if report.get("exit_reason") not in {"report_generated", "gate_block"}:
        errors.append(f"exit_reason={report.get('exit_reason')}")
    if unique_ids != verdict_ids:
        errors.append(f"coverage={len(verdict_ids)}/{len(unique_ids)}")
    if report.get("usage", {}).get("failed_findings", 0):
        errors.append("failed_findings nonzero")
    return errors


def _fresh_errors(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    master_before: dict[str, int],
    master_after: dict[str, int],
) -> list[str]:
    errors = []
    for project in PROJECTS:
        report = after[project]
        usage = report.get("usage", {})
        expected = len(_signature(before[project]))
        if _signature(report) != _signature(before[project]):
            errors.append(f"{project}: verdict/confidence changed")
        if usage.get("reuse_candidates") != expected or usage.get("reused_verdicts") != expected:
            errors.append(f"{project}: reuse != {expected}")
        if usage.get("reevaluated_verdicts") != 0:
            errors.append(f"{project}: unexpected re-evaluation")
        if usage.get("total_tokens") or usage.get("batches"):
            errors.append(f"{project}: LLM was called")
        if _events(_label("a2"), project):
            errors.append(f"{project}: new local events")
        if master_after[project] != master_before[project]:
            errors.append(f"{project}: new master verdict events")
        errors.extend(f"{project}: {error}" for error in _coverage_errors(report))
    return errors


def _revision_errors(
    label: str,
    project: str,
    reason: str,
    previous_ids: dict[str, str],
) -> list[str]:
    report = _report(label, project)
    usage = report.get("usage", {})
    events = _events(label, project)
    errors = []
    if usage.get("reuse_candidates") != len(previous_ids):
        errors.append("wrong candidate count")
    if usage.get("reused_verdicts") != 0:
        errors.append("unexpected reuse")
    if usage.get("reevaluated_verdicts") != len(previous_ids):
        errors.append("wrong re-evaluation count")
    if len(events) != len(previous_ids):
        errors.append(f"events={len(events)}, expected={len(previous_ids)}")
    for event in events:
        if event.get("revision_reason") != reason:
            errors.append(f"{event.get('fp')}: wrong revision reason")
        if event.get("supersedes_verdict_id") != previous_ids.get(event.get("fp")):
            errors.append(f"{event.get('fp')}: wrong supersedes ID")
        if event.get("confidence_level") is None or not event.get("ruleset_hash"):
            errors.append(f"{event.get('fp')}: incomplete new provenance")
    errors.extend(_coverage_errors(report))
    return errors


def _legacy_seed() -> dict[str, str]:
    report = _report(_label("a1"), "aitextgen")
    project = "aitextgen"
    key = _project_key(project)
    now = datetime.now(timezone.utc).isoformat()
    verdicts = _signature(report)
    findings = {item["finding_id"]: item for item in report["findings"]}
    seed_ids = {}
    events = []
    for finding_id in sorted(verdicts):
        seed_id = str(uuid.uuid5(_NAMESPACE, f"{key}:{finding_id}:{PREFIX}-legacy"))
        seed_ids[finding_id] = seed_id
        finding = findings[finding_id]
        events.append(
            {
                "schema_version": 1,
                "client_event_id": seed_id,
                "project_key": key,
                "event_type": "triage_verdicted",
                "at": now,
                "fp": finding_id,
                "verdict_id": seed_id,
                "run_id": f"{PREFIX}-legacy-seed",
                "verdict": verdicts[finding_id][0],
                "verdict_source": "model",
                "actor_id": "legacy-seed",
                "review_status": "unreviewed",
                "explanation": "Controlled legacy event without confidence",
                "evidence": [],
                "agent_version": "legacy-seed",
                "model": "legacy-seed",
                "prompt_sha256": "legacy-seed",
                "scanner": finding.get("scanner"),
                "rule_id": finding.get("rule_id"),
                "ruleset_hash": report.get("scan_meta", {}).get("ruleset_hash"),
                "rule_hash": finding.get("rule_hash"),
                "rule_hash_status": finding.get("rule_hash_status"),
                "created_at": now,
            }
        )
    result = _master_request("/v1/events", project, payload={"events": events})
    rejected = [row for row in result["outcomes"] if row["outcome"].startswith("rejected:")]
    if rejected:
        raise RuntimeError(f"legacy seed rejected: {rejected}")
    return seed_ids


def main() -> None:
    result: dict[str, Any] = {"passed": False, "phases": {}}
    try:
        a1 = _run(_label("a1"), PROJECTS, "0")
        result["phases"]["a1"] = {
            project: {"verdicts": len(_signature(report)), "errors": _coverage_errors(report)}
            for project, report in a1.items()
        }
        if any(item["errors"] for item in result["phases"]["a1"].values()):
            raise RuntimeError("A1 coverage failed")
        previous = {
            project: {event["fp"]: event["verdict_id"] for event in _events(_label("a1"), project)}
            for project in PROJECTS
        }
        master_before = {project: _audit_verdict_count(project) for project in PROJECTS}
        a2 = _run(_label("a2"), PROJECTS, "1h")
        master_after = {project: _audit_verdict_count(project) for project in PROJECTS}
        fresh_errors = _fresh_errors(a1, a2, master_before, master_after)
        result["phases"]["a2_fresh"] = {"reused": 5, "errors": fresh_errors}
        if fresh_errors:
            raise RuntimeError(f"Phase A failed: {fresh_errors}")

        time.sleep(65)
        _run(_label("b"), ("structlog",), "1m")
        expired_errors = _revision_errors(
            _label("b"), "structlog", "ttl_expired", previous["structlog"]
        )
        result["phases"]["b_expired"] = {"reevaluated": 2, "errors": expired_errors}
        if expired_errors:
            raise RuntimeError(f"Phase B failed: {expired_errors}")

        seed_ids = _legacy_seed()
        _run(_label("c"), ("aitextgen",), "1h")
        legacy_errors = _revision_errors(
            _label("c"), "aitextgen", "legacy_confidence_missing", seed_ids
        )
        result["phases"]["c_legacy"] = {
            "reevaluated": 3,
            "seed_ids": seed_ids,
            "errors": legacy_errors,
        }
        if legacy_errors:
            raise RuntimeError(f"Phase C failed: {legacy_errors}")
        result["passed"] = True
    except Exception as exc:
        result["error"] = str(exc)
        OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        raise
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
