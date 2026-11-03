#!/usr/bin/env python3
"""Stage 3.0: category breakdown and SCA package/age analysis for final TPs."""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
ROWS = json.loads((ARTIFACTS / "vibe100-triage.json").read_text())
TP = [row for row in ROWS if row["triage_verdict"] == "TRUE_POSITIVE"]

PKG_PATTERNS = [
    re.compile(r"(?:uses|specifies|contains|of|package|identifies)\s+['\"]?([\w.\-/@~]+)['\"]?\s+(?:version\s+)?\(?v?([0-9][\w.\-]*)\)?", re.I),
    re.compile(r"['\"]([\w.\-/@~]+)['\"]\s*\(v?([0-9][\w.\-]*)\)", re.I),
    re.compile(r"([\w.\-/@~]+)==([0-9][\w.\-]*)"),
]
FIXED_RE = re.compile(r"(?:fixed in|upgrade to|upgrad\w+ to version|patched in|fixed version is|or later[.,]?\s*(?:fixed)?)\s*[v'\"]?([0-9][\w.\-]*)", re.I)
ECOSYSTEMS = {
    "package-lock.json": "npm", "pnpm-lock.yaml": "npm", "yarn.lock": "npm", "bun.lock": "npm",
    "requirements.txt": "PyPI", "uv.lock": "PyPI", "go.mod": "Go", "Cargo.lock": "crates.io",
}


def package_info(row: dict) -> tuple[str | None, str | None, str | None]:
    explanation = row.get("explanation") or ""
    pkg = installed = None
    for pattern in PKG_PATTERNS:
        match = pattern.search(explanation)
        if match:
            pkg, installed = match.group(1), match.group(2)
            break
    fixed_match = FIXED_RE.search(explanation)
    return pkg, installed, fixed_match.group(1) if fixed_match else None


def package_introduced(repo: str, lockfile: str, pkg: str | None) -> dict:
    path = ROOT / "repos" / repo
    result = {"since": None, "age_days_at_scan": None, "history": "unavailable"}
    if not pkg or not (path / ".git").exists():
        return result
    shallow = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-shallow-repository"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    log = []
    for needle in dict.fromkeys((pkg, pkg.lower())):
        log = subprocess.run(
            ["git", "-C", str(path), "log", "--reverse", "--format=%cI", f"-S{needle}", "--", lockfile],
            capture_output=True, text=True, check=False, timeout=30,
        ).stdout.splitlines()
        if log:
            break
    if not log:
        return result
    try:
        introduced = datetime.fromisoformat(log[0])
        scan_date = datetime(2026, 11, 3, tzinfo=timezone.utc)
        result.update(
            since=log[0],
            age_days_at_scan=max(0, (scan_date - introduced).days),
            history="shallow clone; lower bound only" if shallow == "true" else "full clone",
        )
    except ValueError:
        pass
    return result


def main() -> None:
    sca = [r for r in TP if r["scanner"] == "trivy" and str(r["rule"]).startswith(("CVE", "GHSA"))]
    iac = [r for r in TP if r["scanner"] == "trivy" and r not in sca]
    secrets = [r for r in TP if r["scanner"] == "gitleaks"]
    sast = [r for r in TP if r["scanner"] == "semgrep"]

    for row in sca:
        row["package"], row["installed"], row["fixed"] = package_info(row)

    packages = defaultdict(lambda: {"count": 0, "cves": Counter(), "repos": set()})
    for row in sca:
        pkg = row["package"] or "unparsed"
        packages[pkg]["count"] += 1
        packages[pkg]["cves"][row["rule"]] += 1
        packages[pkg]["repos"].add(row["repo"])
    package_summary = [
        {"package": pkg, "findings": data["count"], "repos": len(data["repos"]),
         "top_cves": data["cves"].most_common(3)}
        for pkg, data in packages.items()
    ]
    package_summary.sort(key=lambda item: -item["findings"])

    critical = [r for r in sca if r["severity"] == "critical"]
    top_critical = Counter(r["rule"] for r in critical).most_common(5)
    dangerous = []
    for cve, count in top_critical:
        instances = [r for r in critical if r["rule"] == cve]
        sample = next((r for r in instances if r["package"]), instances[0])
        age = package_introduced(sample["repo"], sample["file"], sample["package"])
        dangerous.append({
            "cve": cve, "findings": count, "repos": len({r["repo"] for r in instances}),
            "sample_repo": sample["repo"], "sample_file": sample["file"],
            "package": sample["package"], "installed": sample["installed"],
            "fixed": sample["fixed"], **age,
        })

    analysis = {
        "total_tp": len(TP),
        "categories": {"sca": len(sca), "iac": len(iac), "secrets": len(secrets), "sast": len(sast)},
        "sca": {
            "critical": len(critical),
            "high": sum(r["severity"] == "high" for r in sca),
            "ecosystems": Counter(ECOSYSTEMS.get((r["file"] or "").split("/")[-1], "other") for r in sca),
            "top_cves": Counter(r["rule"] for r in sca).most_common(15),
            "top_packages": package_summary[:15],
            "top_critical_age": dangerous,
            "top_repos_critical": Counter(r["repo"] for r in critical).most_common(10),
        },
        "iac": [{"repo": r["repo"], "file": r["file"], "rule": r["rule"], "severity": r["severity"]} for r in iac],
        "secrets": [{"repo": r["repo"], "file": r["file"], "line": r["line"], "rule": r["rule"]} for r in secrets],
        "sast": [{"repo": r["repo"], "file": r["file"], "line": r["line"], "rule": r["rule"]} for r in sast],
    }
    (ARTIFACTS / "vibe100-findings-analysis.json").write_text(
        json.dumps(analysis, indent=1, ensure_ascii=False, default=lambda value: dict(value)) + "\n"
    )
    print(json.dumps(analysis["categories"], indent=1))
    print(json.dumps(dangerous, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
