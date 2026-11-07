#!/usr/bin/env python3
"""GD-12: measure deterministic CVE signals on existing findings.

For every run with both a report.json (trivy findings carry
package/installed_version/fixed_version in metadata) and a verdict journal,
compute scanner-independent signals and their agreement with model verdicts:

- version_out_of_range: installed_version >= fixed_version (scanner range
  contradicts the finding -> deterministic FP candidate);
- fixed_version_missing: no fix published;
- (dependency scope is NOT measurable from artifacts; manifests are not in
  the report — recorded as a limitation, per GD-12 measurement-first rule).

Output: artifacts/cve-signals.json with the signal x verdict contingency and
the share of CVE FALSE_POSITIVEs explained by version_out_of_range. Adoption
gate (GD-12): propose ADR-0018 rules only if that share is >= 30-40%.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

_ADOPTION_THRESHOLD = 0.30


def _version_tuple(text: str) -> tuple[Any, ...] | None:
    parts = re.findall(r"\d+|[a-z]+", text.lower())
    if not parts or not parts[0].isdigit():
        return None
    return tuple(int(p) if p.isdigit() else p for p in parts)


def _out_of_range(installed: str, fixed: str) -> bool | None:
    """True when installed >= the fixed release of its own major branch.

    Fixed lists are per-branch ("1.16.0, 0.32.0"); comparing against the
    global min/max misclassifies multi-branch fixes. None when no same-major
    fixed release exists or versions are unparseable.
    """
    inst = _version_tuple(installed)
    candidates = [v for v in (_version_tuple(f) for f in re.split(r"[,\s]+", fixed) if f) if v]
    if not inst or not candidates:
        return None
    same_major = [v for v in candidates if v[0] == inst[0]]
    if not same_major:
        return None
    branch_fixed = min(same_major)
    length = max(len(inst), len(branch_fixed))
    padded = inst + (0,) * (length - len(inst))
    return padded >= branch_fixed


def _load_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main() -> None:
    contingency: dict[str, Counter] = {}
    rows = 0
    fps: set[str] = set()
    runs_used: list[str] = []
    for report_path in sorted(ROOT.glob("artifacts/*/report.json")):
        run_id = report_path.parent.name
        verdicts = _load_lines(ROOT / "runtime" / f"data-{run_id}" / "triage_verdicts.ndjson")
        cve_verdicts = {
            v["fp"]: v["verdict"]
            for v in verdicts
            if v.get("prompt_mode") == "cve" and v.get("fp") and not v.get("failure_reason")
        }
        if not cve_verdicts:
            continue
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        runs_used.append(run_id)
        for finding in report.get("findings", []):
            fp = finding.get("fingerprint")
            if fp not in cve_verdicts:
                continue
            metadata = finding.get("metadata") or {}
            installed = metadata.get("installed_version") or ""
            fixed = metadata.get("fixed_version") or ""
            if not installed:
                signal = "installed_version_missing"
            elif not fixed:
                signal = "fixed_version_missing"
            else:
                oor = _out_of_range(installed, fixed)
                signal = {True: "version_out_of_range", False: "in_range", None: "unparseable"}[oor]
            verdict = cve_verdicts[fp]
            contingency.setdefault(signal, Counter())[verdict] += 1
            rows += 1
            fps.add(fp)

    explained = contingency.get("version_out_of_range", Counter()).get("FALSE_POSITIVE", 0)
    total_fp = sum(c.get("FALSE_POSITIVE", 0) for c in contingency.values())
    share = round(explained / total_fp, 4) if total_fp else None
    oor = contingency.get("version_out_of_range", Counter())
    tp_contradicted = oor.get("TRUE_POSITIVE", 0)
    total_tp = sum(c.get("TRUE_POSITIVE", 0) for c in contingency.values())
    artifact = {
        "runs": runs_used,
        "cve_rows": rows,
        "distinct_fingerprints": len(fps),
        "signal_x_verdict": {signal: dict(c) for signal, c in sorted(contingency.items())},
        "cve_fp_explained_by_version_out_of_range": {
            "explained": explained,
            "total_fp": total_fp,
            "share": share,
            "adoption_threshold": _ADOPTION_THRESHOLD,
            "recommend": "propose version_out_of_range to ADR-0018"
            if share is not None and share >= _ADOPTION_THRESHOLD
            else "below threshold or no data — do not integrate",
        },
        "model_tp_contradicted_by_version_out_of_range": {
            "count": tp_contradicted,
            "total_tp": total_tp,
            "share": round(tp_contradicted / total_tp, 4) if total_tp else None,
            "note": (
                "model confirmed TP although installed >= same-major-branch fixed "
                "version; sample-audit before treating as model misses"
            ),
        },
        "limitations": [
            "dependency scope (dev/prod) not present in report.json; needs manifest parse",
            "version compare is numeric-tuple, same-major branch; distro epochs/pre-release tags may misclassify",
            "duplicate (fp, verdict) rows across sweep arms are counted per run",
        ],
    }
    output = ROOT / "artifacts" / "cve-signals.json"
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"runs": len(runs_used), "cve_rows": rows, "fp_share_explained": share}))


if __name__ == "__main__":
    main()
