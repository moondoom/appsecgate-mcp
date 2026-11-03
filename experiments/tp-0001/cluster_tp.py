#!/usr/bin/env python3
"""Stage 3.0: кластеризация финальных TP по метаданным репозиториев."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRIAGE = json.loads((ROOT / "artifacts" / "vibe100-triage.json").read_text())
FUNNEL = {x["repo"]: x for x in json.loads((ROOT / "artifacts" / "vibe100-funnel.json").read_text())}

tp = [r for r in TRIAGE if r["triage_verdict"] == "TRUE_POSITIVE"]


def stars_bucket(s):
    if s is None: return "unknown"
    if s < 100: return "<100"
    if s < 1000: return "100-1k"
    if s < 10000: return "1k-10k"
    return "10k+"


def contrib_bucket(c):
    if c is None: return "unknown"
    if c <= 5: return "<=5"
    if c <= 20: return "6-20"
    if c <= 100: return "21-100"
    return "100+"


def group_stats(rows, keyfn):
    groups = defaultdict(list)
    for r in rows:
        groups[keyfn(r)].append(r)
    out = {}
    for k, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        repos = {r["repo"] for r in rs}
        sev = Counter(r["severity"] for r in rs)
        rules = Counter((r["scanner"], (r["rule"] or "")[:60]) for r in rs)
        out[str(k)] = {
            "tp": len(rs),
            "repos": len(repos),
            "tp_per_repo": round(len(rs) / max(len(repos), 1), 1),
            "severity": dict(sev.most_common()),
            "top_rules": [f"{s}/{r} ({n})" for (s, r), n in rules.most_common(5)],
        }
    return out


clusters = {
    "total_tp": len(tp),
    "by_contrast": group_stats(tp, lambda r: "contrast" if r["contrast"] else "vibe"),
    "by_lang": group_stats(tp, lambda r: r.get("lang") or "unknown"),
    "by_stars": group_stats(tp, lambda r: stars_bucket(r.get("stars"))),
    "by_contributors": group_stats(tp, lambda r: contrib_bucket(r.get("contributors"))),
    "by_agent": group_stats(
        [r for r in tp if r.get("agents_detected")],
        lambda r: ",".join(sorted(r["agents_detected"])[:2]),
    ),
    "by_scanner": group_stats(tp, lambda r: r.get("scanner") or "unknown"),
}

# нормировка: TP на 100k строк кода в кластере
repo_lines = {r["repo"]: FUNNEL.get(r["repo"], {}).get("lines") or 0 for r in tp}
for section in ("by_contrast", "by_lang", "by_stars", "by_contributors"):
    rows_by_key = defaultdict(set)
    keyfn = {
        "by_contrast": lambda r: "contrast" if r["contrast"] else "vibe",
        "by_lang": lambda r: r.get("lang") or "unknown",
        "by_stars": lambda r: stars_bucket(r.get("stars")),
        "by_contributors": lambda r: contrib_bucket(r.get("contributors")),
    }[section]
    for r in tp:
        rows_by_key[str(keyfn(r))].add(r["repo"])
    for k, repos in rows_by_key.items():
        lines = sum(repo_lines.get(rp, 0) for rp in repos)
        if k in clusters[section] and lines:
            clusters[section][k]["tp_per_100k_lines"] = round(
                clusters[section][k]["tp"] / lines * 100_000, 1
            )

(ROOT / "artifacts" / "vibe100-clusters.json").write_text(
    json.dumps(clusters, indent=1, ensure_ascii=False)
)

# md-сводка
md = ["# vibe100: кластеризация TP по метаданным", ""]
for section, data in clusters.items():
    if section == "total_tp":
        md.append(f"Всего TP: {data}\n")
        continue
    md.append(f"## {section}")
    for k, v in data.items():
        norm = f", {v['tp_per_100k_lines']} TP/100k строк" if "tp_per_100k_lines" in v else ""
        md.append(f"- **{k}**: {v['tp']} TP в {v['repos']} репо ({v['tp_per_repo']}/репо{norm})")
        md.append(f"  - severity: {v['severity']}")
        md.append(f"  - топ правил: {', '.join(v['top_rules'])}")
    md.append("")
(ROOT / "artifacts" / "vibe100-clusters.md").write_text("\n".join(md) + "\n")
print("\n".join(md[:40]))
