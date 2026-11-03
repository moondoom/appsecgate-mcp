#!/usr/bin/env python3
"""Stage 3.0: сбор TP/NEEDS_REVIEW + воронка + автотриаж."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LABELS = ("vibe100", "vibe100fix")
MODEL, PAR = "gemmaq3", 4

meta_list = json.loads((ROOT / "artifacts" / "vibe100-final.json").read_text())
meta = {item["name"]: item for item in meta_list}

# --- эвристики автотриажа (аналог reachability-разбора oss20) ---
TEST_PATH = re.compile(
    r"(^|/)(tests?|testdata|fixtures?|examples?|docs?|samples?|__tests__|spec|e2e)(/|$)|"
    r"(_test\.|_spec\.|\.test\.|\.spec\.)",
    re.IGNORECASE,
)
BUILD_DEP_FILES = re.compile(r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml)$")
DOC_FILES = re.compile(r"\.(md|rst|txt)$", re.IGNORECASE)


def auto_assess(row: dict) -> tuple[str, str]:
    """Грубая переоценка вердикта модели. Возвращает (assessment, причина)."""
    f = (row.get("file") or "").lower()
    rule = row.get("rule") or ""
    if DOC_FILES.search(f):
        return "LIKELY_FP", "документация, не код"
    if TEST_PATH.search(f):
        return "LIKELY_FP", "tests/fixtures/examples — недостижимо в проде"
    if BUILD_DEP_FILES.search(f):
        return "NEEDS_HUMAN", "lockfile: зависит от dev/prod и деплоя (см. прецедент retrofit)"
    if row.get("scanner") == "trivy" and rule.startswith(("CVE", "GHSA")):
        return "NEEDS_HUMAN", "SCA: нужна проверка fixed-версии и достижимости"
    return "PLAUSIBLE", "нет очевидных признаков FP"


rows: list[dict] = []
funnel: list[dict] = []
missing: list[str] = []

for report_path in sorted(p for lbl in LABELS for p in ROOT.glob(f"artifacts/{lbl}-{MODEL}-p{PAR}-*/report.json")):
    rep = json.loads(report_path.read_text())
    repo = rep["run_id"].split(f"-{MODEL}-p{PAR}-")[-1]
    m = meta.get(repo, {})

    # raw-находки сканеров из agent.log
    raw = None
    log = report_path.parent / "agent.log"
    if log.exists():
        for line in log.read_text(errors="replace").splitlines():
            mm = re.search(r"scan done .* findings=(\d+)", line)
            if mm:
                raw = int(mm.group(1))

    # объём просканированного кода: строки в файлах с исходниками/IaC
    SRC_EXT = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rb", ".php",
               ".java", ".yaml", ".yml", ".tf", ".sh", ".cs", ".kt"}
    files_count, code_lines = 0, 0
    repo_dir = ROOT / "repos" / repo
    if repo_dir.is_dir():
        for p in repo_dir.rglob("*"):
            if not p.is_file() or ".git" in p.parts:
                continue
            if p.suffix.lower() not in SRC_EXT and p.name != "Dockerfile":
                continue
            files_count += 1
            try:
                code_lines += sum(1 for _ in p.open("rb"))
            except OSError:
                pass

    if "verdicts" not in rep:
        if repo not in {x["repo"] for x in funnel}:
            missing.append(repo)
        continue
    if repo in missing:
        missing.remove(repo)

    fmap = {f.get("finding_id") or f.get("fingerprint"): f for f in rep.get("findings", [])}
    vcount = Counter(v.get("verdict") for v in rep["verdicts"])
    funnel.append(
        {
            "repo": repo,
            "contrast": m.get("contrast"),
            "lang": m.get("lang"),
            "stars": m.get("stars"),
            "contributors": m.get("contributors"),
            "agents_detected": m.get("agents_detected"),
            "files": files_count,
            "lines": code_lines,
            "raw_findings": raw,
            "deduped": len(rep.get("findings", [])),
            "tp": vcount.get("TRUE_POSITIVE", 0),
            "nr": vcount.get("NEEDS_REVIEW", 0),
            "fp": vcount.get("FALSE_POSITIVE", 0),
        }
    )

    for v in rep["verdicts"]:
        if v.get("verdict") not in ("TRUE_POSITIVE", "NEEDS_REVIEW"):
            continue
        f = fmap.get(v["finding_id"], {})
        row = {
            "repo": repo,
            "contrast": m.get("contrast"),
            "stars": m.get("stars"),
            "lang": m.get("lang"),
            "verdict": v["verdict"],
            "rule": f.get("rule_id"),
            "line": f.get("line_start"),
            "file": f.get("file_path"),
            "severity": f.get("severity"),
            "scanner": f.get("scanner"),
            "explanation": v.get("explanation"),
            "patch": v.get("patch"),
            "agents_detected": m.get("agents_detected"),
            "contributors": m.get("contributors"),
            "last_commit_at": m.get("last_commit_at"),
        }
        row["auto_assessment"], row["auto_reason"] = auto_assess(row)
        rows.append(row)

(ROOT / "artifacts" / "vibe100-tp-review.json").write_text(
    json.dumps(rows, indent=1, ensure_ascii=False)
)
(ROOT / "artifacts" / "vibe100-funnel.json").write_text(
    json.dumps(funnel, indent=1, ensure_ascii=False)
)

# --- сводка ---
def agg(items, key):
    return sum(x[key] or 0 for x in items)


tot = {
    "repos": len(funnel),
    "files": agg(funnel, "files"),
    "lines": agg(funnel, "lines"),
    "raw": agg(funnel, "raw_findings"),
    "deduped": agg(funnel, "deduped"),
    "tp": agg(funnel, "tp"),
    "nr": agg(funnel, "nr"),
    "fp": agg(funnel, "fp"),
}
vibe_f = [x for x in funnel if x["contrast"] is False]
con_f = [x for x in funnel if x["contrast"] is True]
assess = Counter(r["auto_assessment"] for r in rows)

md = [
    "# vibe100: воронка и находки TP/NEEDS_REVIEW",
    "",
    "## Воронка (все репо)",
    f"0. Просканировано: {tot['files']} файлов исходников, {tot['lines']} строк ({tot['repos']} репо)",
    f"1. SAST/SCA/IaC сырые: {tot['raw']}",
    f"2. После дедупликации (показано): {tot['deduped']}",
    f"3. Дешёвая модель (gemmaq3): TP {tot['tp']} | NEEDS_REVIEW {tot['nr']} | FP {tot['fp']}",
    f"4. К дорогой модели/AppSec (TP+NR): {tot['tp'] + tot['nr']}",
    "",
    "## Воронка vibe vs contrast",
    f"- vibe ({len(vibe_f)} репо): raw {agg(vibe_f,'raw_findings')} → dedup {agg(vibe_f,'deduped')} → TP+NR {agg(vibe_f,'tp')+agg(vibe_f,'nr')}",
    f"- contrast ({len(con_f)} репо): raw {agg(con_f,'raw_findings')} → dedup {agg(con_f,'deduped')} → TP+NR {agg(con_f,'tp')+agg(con_f,'nr')}",
    "",
    "## Автотриаж собранных TP/NR (мои эвристики)",
    *[f"- {k}: {v}" for k, v in assess.most_common()],
    "",
    "## По severity",
    *[f"- {k}: {v}" for k, v in Counter(r['severity'] for r in rows).most_common()],
    "",
    "## Топ правил",
    *[f"- {k}: {v}" for k, v in Counter(r['rule'] for r in rows).most_common(15)],
    "",
    "## Топ репозиториев по TP+NR",
    *[f"- {k}: {v}" for k, v in Counter(r['repo'] for r in rows).most_common(20)],
]
(ROOT / "artifacts" / "vibe100-tp-review.md").write_text("\n".join(md) + "\n")

print(json.dumps({"funnel": tot, "auto_assess": dict(assess), "missing": missing}, indent=1))
