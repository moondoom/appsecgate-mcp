#!/usr/bin/env python3
"""Stage 3.0: экспорт протриаженных находок (TP) в SARIF 2.1.0.

Источник: artifacts/vibe100-triage.json (только финальные TRUE_POSITIVE).
Выход: artifacts/vibe100-sarif/<repo>.sarif + artifacts/vibe100-all.sarif.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROWS = json.loads((ROOT / "artifacts" / "vibe100-triage.json").read_text())

SEVERITY_TO_LEVEL = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}


def build_sarif(repo: str, rows: list[dict], path_prefix: str = "") -> dict:
    rules: dict[str, dict] = {}
    results = []
    for r in rows:
        rule_id = r.get("rule") or "unknown"
        scanner = r.get("scanner") or "unknown"
        full_id = f"{scanner}/{rule_id}"
        if full_id not in rules:
            rules[full_id] = {
                "id": full_id,
                "name": rule_id,
                "shortDescription": {"text": rule_id},
                "properties": {"scanner": scanner, "severity": r.get("severity")},
            }
        uri = path_prefix + (r.get("file") or "").replace("\\", "/")
        result = {
            "ruleId": full_id,
            "level": SEVERITY_TO_LEVEL.get((r.get("severity") or "").lower(), "warning"),
            "message": {"text": r.get("explanation") or rule_id},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": uri},
                        "region": {"startLine": r.get("line") or 1},
                    }
                }
            ],
            "properties": {
                "appsecgate/verdict": r.get("verdict"),
                "appsecgate/triage": r.get("triage_verdict"),
                "appsecgate/triage_reason": r.get("triage_reason"),
                "appsecgate/repo": repo,
                "appsecgate/contrast": r.get("contrast"),
            },
        }
        results.append(result)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "AppSecGate MCP",
                        "informationUri": "https://habr.com/ru/articles/1099840/",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }


def main() -> None:
    out_dir = ROOT / "artifacts" / "vibe100-sarif"
    out_dir.mkdir(exist_ok=True)
    tp = [r for r in ROWS if r.get("triage_verdict") == "TRUE_POSITIVE"]

    by_repo: dict[str, list[dict]] = {}
    for r in tp:
        by_repo.setdefault(r["repo"], []).append(r)

    for repo, rows in sorted(by_repo.items()):
        (out_dir / f"{repo}.sarif").write_text(
            json.dumps(build_sarif(repo, rows), indent=1, ensure_ascii=False)
        )

    # сводный файл: один run на репозиторий
    combined = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            build_sarif(repo, rows, path_prefix=f"experiments/tp-0001/repos/{repo}/")["runs"][0]
            for repo, rows in sorted(by_repo.items())
        ],
    }
    (ROOT / "artifacts" / "vibe100-all.sarif").write_text(
        json.dumps(combined, indent=1, ensure_ascii=False)
    )
    print(f"repos: {len(by_repo)}, findings: {len(tp)} -> {out_dir} + vibe100-all.sarif")


if __name__ == "__main__":
    main()
