#!/usr/bin/env python3
"""Stage 3.0: автотриаж TP/NEEDS_REVIEW находок (v2 — с проверкой версий)."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROWS = json.loads((ROOT / "artifacts" / "vibe100-tp-review.json").read_text())

NONPROD = re.compile(r"(^|/)(tests?|testdata|fixtures?|examples?|docs?|website|samples?|__tests__|e2e)(/|$)", re.I)
PLACEHOLDER = re.compile(
    r"(example|sample|placeholder|changeme|change[_-]?me|your[_-]?(api[_-]?)?key|xx{3,}|"
    r"dummy|fake|test[_-]?key|123456|abcdef|<[a-z_]+>|\$\{|localhost|admin123|password123)",
    re.I,
)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

PKG_PATTERNS = [
    re.compile(r"(?:uses|specifies|contains|of|package)\s+['\"]?([\w.\-/@~]+)['\"]?\s+(?:version\s+)?\(?v?([0-9][\w.\-]*)\)?", re.I),
    re.compile(r"['\"]([\w.\-/@~]+)['\"]\s*\(v?([0-9][\w.\-]*)\)", re.I),
    re.compile(r"([\w.\-/@~]+)==([0-9][\w.\-]*)"),
]
FIXED_RE = re.compile(
    r"(?:fixed in|upgrade to|upgrad\w+ to version|patched in|fixed version is|or later[.,]?\s*(?:fixed)?)\s*[v'\"]?([0-9][\w.\-]*)",
    re.I,
)


def ver_tuple(v: str) -> tuple:
    parts = re.split(r"[.\-+]", v)
    out = []
    for p in parts:
        out.append(int(p) if p.isdigit() else 0)
    return tuple(out)


def ver_lt(a: str, b: str) -> bool | None:
    ta, tb = ver_tuple(a), ver_tuple(b)
    n = max(len(ta), len(tb))
    ta += (0,) * (n - len(ta))
    tb += (0,) * (n - len(tb))
    if ta == tb:
        return None
    return ta < tb


def extract_pkg(expl: str) -> tuple[str | None, str | None, str | None]:
    pkg = installed = fixed = None
    for pat in PKG_PATTERNS:
        m = pat.search(expl)
        if m:
            pkg, installed = m.group(1), m.group(2)
            break
    m = FIXED_RE.search(expl)
    if m:
        fixed = m.group(1)
    return pkg, installed, fixed


def repo_path(repo: str, f: str | None) -> Path | None:
    if not f:
        return None
    p = ROOT / "repos" / repo / f
    return p if p.exists() else None


def lock_is_dev(lock_path: Path, pkg: str, lock_kind: str) -> bool | None:
    try:
        if lock_kind == "package-lock":
            lock = json.loads(lock_path.read_text())
            for path, entry in lock.get("packages", {}).items():
                if path.endswith(f"node_modules/{pkg}"):
                    return bool(entry.get("dev"))
        elif lock_kind == "pnpm":
            for m in re.finditer(rf"{re.escape(pkg)}@[\w.\-]+.*?(?=\n  \S|\Z)", lock_path.read_text(), re.DOTALL):
                if "dev: true" in m.group(0):
                    return True
            return False
    except Exception:
        return None
    return None


def triage_sca(row: dict) -> tuple[str, str]:
    f = row.get("file") or ""
    if NONPROD.search(f):
        return "FALSE_POSITIVE", f"auto: непродакшн-путь ({f.split('/')[0]}/)"
    expl = row.get("explanation") or ""
    pkg, installed, fixed = extract_pkg(expl)
    vuln_confirmed = None
    if installed and fixed:
        lt = ver_lt(installed, fixed)
        vuln_confirmed = lt if lt is not None else False

    base = f.split("/")[-1]
    p = repo_path(row["repo"], f)

    if vuln_confirmed is False:
        return "FALSE_POSITIVE", f"auto: {pkg} {installed} не ниже fixed {fixed}"

    if base == "go.mod" and p and pkg:
        try:
            for line in p.read_text().splitlines():
                if pkg in line:
                    if "// indirect" in line:
                        return "NEEDS_HUMAN", f"auto: indirect {pkg}, достижимость неясна"
                    v = "версия подтверждена ниже fixed" if vuln_confirmed else "версия не сверена"
                    return "TRUE_POSITIVE", f"auto: прямая зависимость {pkg} в go.mod, {v}"
        except Exception:
            pass
    if base in ("requirements.txt",) and p and pkg:
        v = f"{installed} < {fixed}" if vuln_confirmed else "версия не сверена"
        return "TRUE_POSITIVE", f"auto: {pkg} запинен в requirements.txt, {v}"
    if base == "package-lock.json" and vuln_confirmed and not pkg:
        return "TRUE_POSITIVE", f"auto: lockfile, версия {installed} < fixed {fixed}"
    if base == "package-lock.json" and p and pkg:
        dev = lock_is_dev(p, pkg, "package-lock")
        if dev is True:
            return "FALSE_POSITIVE", f"auto: devDependency {pkg}"
        if dev is False:
            return "TRUE_POSITIVE", f"auto: prod-зависимость {pkg} в lockfile"
    if base in ("yarn.lock", "bun.lock", "uv.lock", "Cargo.lock"):
        if vuln_confirmed:
            return "TRUE_POSITIVE", f"auto: {base}, {pkg} {installed} < fixed {fixed}"
        return "NEEDS_HUMAN", f"auto: {base}, dev/prod не определить"
    if base == "pnpm-lock.yaml" and vuln_confirmed and not pkg:
        return "TRUE_POSITIVE", f"auto: pnpm-lock, версия {installed} < fixed {fixed}"
    if base == "pnpm-lock.yaml" and p and pkg:
        dev = lock_is_dev(p, pkg, "pnpm")
        if dev is True:
            return "FALSE_POSITIVE", f"auto: devDependency {pkg} (pnpm)"
        if dev is False:
            return "TRUE_POSITIVE", f"auto: prod-зависимость {pkg} (pnpm)"
    if "Dockerfile" in base:
        return "NEEDS_HUMAN", "auto: Dockerfile, нужен глаз"
    if base.endswith((".lock", "lock.yaml", "lock.json", ".mod")) or base == "requirements.txt":
        if p is not None:
            return "TRUE_POSITIVE", f"auto: {base} существует, доверяем trivy range-match"
    return "NEEDS_HUMAN", f"auto: {base}, манифест не покрыт триажем"


def triage_secret(row: dict) -> tuple[str, str]:
    f = row.get("file") or ""
    if NONPROD.search(f) or re.search(r"\.(md|rst|txt)$", f, re.I):
        return "FALSE_POSITIVE", "auto: docs/tests/fixtures"
    p = repo_path(row["repo"], f)
    if p:
        try:
            lines = p.read_text(errors="replace").splitlines()
            ln = (row.get("line") or 1) - 1
            text = "\n".join(lines[max(0, ln - 2): ln + 2])
            if PLACEHOLDER.search(text):
                return "FALSE_POSITIVE", "auto: плейсхолдер рядом со строкой"
            if UUID_RE.search(text):
                return "FALSE_POSITIVE", "auto: UUID, не секрет"
        except Exception:
            pass
    if "Dockerfile" in f:
        return "NEEDS_HUMAN", "auto: секрет в Dockerfile, нужен глаз"
    return "NEEDS_HUMAN", "auto: секрет, нужен глаз"


def triage_code(row: dict) -> tuple[str, str]:
    f = row.get("file") or ""
    if NONPROD.search(f) or "/_archive/" in f or "/scripts/" in f:
        return "FALSE_POSITIVE", "auto: непродакшн/архивный код"
    return "NEEDS_HUMAN", "auto: semgrep-находка, нужен разбор кода"


out = []
for row in ROWS:
    if row.get("scanner") == "trivy" and not str(row.get("rule", "")).startswith(("CVE", "GHSA")):
        v, why = triage_secret(row)  # trivy misconfig/secret правила
    elif row.get("scanner") == "trivy":
        v, why = triage_sca(row)
    elif row.get("scanner") == "gitleaks":
        v, why = triage_secret(row)
    else:
        v, why = triage_code(row)
    row["triage_verdict"], row["triage_reason"] = v, why
    out.append(row)

(ROOT / "artifacts" / "vibe100-triage.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))

print(Counter(r["triage_verdict"] for r in out))
print("\nмодель × триаж:")
for k, v in Counter((r["verdict"], r["triage_verdict"]) for r in out).most_common():
    print(" ", k, v)
print("\nNEEDS_HUMAN по причинам:")
for k, v in Counter(r["triage_reason"] for r in out if r["triage_verdict"] == "NEEDS_HUMAN").most_common(10):
    print(" ", v, k)
