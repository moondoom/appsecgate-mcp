from __future__ import annotations

import json
from typing import Any


def format_report(report: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, sort_keys=True)
    gate = report["GateSummary"]
    lines = [
        f"# AppSecGate RO report `{report['run_id']}`",
        f"Model: `{report['model']}`",
        f"Findings: {len(report['findings'])}; verdicts: {len(report['verdicts'])}",
        f"Gate: {'BLOCK' if gate.get('should_fail') else 'PASS'}",
        "",
    ]
    for verdict in report["verdicts"]:
        lines.append(f"## {verdict['finding_id']} — {verdict['verdict']}")
        if verdict["explanation"]:
            lines.append(verdict["explanation"])
        if verdict["patch"]:
            patch = verdict["patch"]
            if not isinstance(patch, str):
                patch = json.dumps(patch, ensure_ascii=False, indent=2)
            lines.extend(["```diff", patch, "```"])
        lines.append("")
    for warning in report["warnings"]:
        lines.append(f"Warning: {warning}")
    return "\n".join(lines).rstrip()
