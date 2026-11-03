#!/usr/bin/env python3
"""Stage 3.0: обогащение shortlist метаданными репозиториев для кластеризации."""
from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FINAL = json.loads((ROOT / "artifacts" / "vibe100-final.json").read_text())

AGENT_PATTERNS = {
    "claude": r"claude( code)?|anthropic",
    "cursor": r"cursor",
    "codex": r"codex|openai codex",
    "copilot": r"copilot",
    "cline": r"cline",
    "windsurf": r"windsurf",
    "aider": r"aider",
    "gemini": r"gemini",
    "chatgpt": r"chatgpt|gpt-4",
}


def readme_text(full_name: str) -> str:
    for branch in ("main", "master"):
        for fname in ("README.md", "readme.md", "README.ru.md"):
            try:
                url = f"https://raw.githubusercontent.com/{full_name}/{branch}/{fname}"
                with urllib.request.urlopen(url, timeout=15) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception:
                continue
    return ""


def contributors_count(full_name: str) -> int | None:
    # HTML-страница репо (без API rate-limit)
    try:
        req = urllib.request.Request(
            f"https://github.com/{full_name}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", "replace")
        m = re.search(r'contributors[^0-9]{0,200}?(\d[\d,]*)\s*(?:contributors|</span>)', html, re.I)
        if m:
            return int(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None


def git_meta(repo: str) -> dict:
    d = ROOT / "repos" / repo
    out = {}
    try:
        log = subprocess.run(
            ["git", "-C", str(d), "log", "-1", "--format=%cI|%an"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        if "|" in log:
            out["last_commit_at"], out["last_commit_author"] = log.split("|", 1)
    except Exception:
        pass
    return out


def main() -> None:
    for i, it in enumerate(FINAL):
        repo = it["name"]
        readme = readme_text(it["full_name"]).lower()
        agents = [a for a, pat in AGENT_PATTERNS.items() if re.search(pat, readme)]
        it["agents_detected"] = agents
        it["contributors"] = contributors_count(it["full_name"])
        it.update(git_meta(repo))
        it["readme_len"] = len(readme)
        print(f"{i+1}/{len(FINAL)} {repo}: agents={agents} contrib={it['contributors']}")
        time.sleep(1)
    (ROOT / "artifacts" / "vibe100-final.json").write_text(
        json.dumps(FINAL, indent=1, ensure_ascii=False)
    )
    print("saved")


if __name__ == "__main__":
    main()
