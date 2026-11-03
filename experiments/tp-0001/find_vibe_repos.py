#!/usr/bin/env python3
"""Stage 3.0 sourcing: поиск vibe-code и контрастных репозиториев через GitHub Search API."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "artifacts" / "vibe100-shortlist.json"

LANGS = "python,javascript,typescript,go,ruby,php,java"

VIBE_QUERIES = [
    '"vibe coded" in:readme stars:50..5000',
    '"vibe-coded" in:readme stars:50..5000',
    '"vibe coding" in:readme stars:50..5000',
    '"built with Claude" in:readme stars:50..5000',
    '"built with Cursor" in:readme stars:50..5000',
    '"written by AI" in:readme stars:50..5000',
    '"100% AI" in:readme stars:50..5000',
    '"AI-generated" in:readme stars:50..5000',
    '"coded by Claude" in:readme stars:50..5000',
    '"built entirely with AI" in:readme stars:50..5000',
    '"vibe code" in:description stars:50..5000',
    '"built with Claude Code" in:readme stars:50..5000',
]

CONTRAST_QUERIES = [
    "stars:500..5000 language:python pushed:>2025-06-01",
    "stars:500..5000 language:javascript pushed:>2025-06-01",
    "stars:500..5000 language:typescript pushed:>2025-06-01",
    "stars:500..5000 language:go pushed:>2025-06-01",
    "stars:500..5000 language:php pushed:>2025-06-01",
    "stars:500..5000 language:ruby pushed:>2025-06-01",
]

AI_SIGNALS = (
    "vibe cod", "built with claude", "built with cursor", "written by ai",
    "100% ai", "ai-generated", "coded by claude", "built entirely with ai",
    "claude code", "vibecod",
)


def search(query: str, per_page: int = 30) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "per_page": per_page, "sort": "stars"})
    req = urllib.request.Request(
        f"https://api.github.com/search/repositories?{params}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "appsecgate-tp0001"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("items", [])
    except urllib.error.HTTPError as e:
        print(f"  search fail {e.code}: {query[:60]}")
        return []


def main() -> None:
    seen: dict[str, dict] = {}

    for q in VIBE_QUERIES:
        print("vibe:", q)
        for item in search(q):
            seen[item["full_name"]] = {
                "name": item["name"],
                "full_name": item["full_name"],
                "url": item["html_url"],
                "clone_url": item["clone_url"],
                "stars": item["stargazers_count"],
                "lang": (item.get("language") or "").lower(),
                "pushed_at": item["pushed_at"],
                "description": item.get("description") or "",
                "vibe_signal": q.split(" in:")[0],
                "contrast": False,
            }
        time.sleep(7)  # 10 req/min лимит

    for q in CONTRAST_QUERIES:
        print("contrast:", q)
        for item in search(q, per_page=10):
            fn = item["full_name"]
            if fn in seen:
                continue
            seen[fn] = {
                "name": item["name"],
                "full_name": fn,
                "url": item["html_url"],
                "clone_url": item["clone_url"],
                "stars": item["stargazers_count"],
                "lang": (item.get("language") or "").lower(),
                "pushed_at": item["pushed_at"],
                "description": item.get("description") or "",
                "vibe_signal": None,
                "contrast": True,
            }
        time.sleep(7)

    items = list(seen.values())
    # фильтр языков
    allowed = set(LANGS.split(","))
    items = [i for i in items if i["lang"] in allowed]
    # контрастные, у которых README/description содержит AI-сигнал — перекрашиваем
    for it in items:
        text = (it["description"] or "").lower()
        if it["contrast"] and any(s in text for s in AI_SIGNALS):
            it["contrast"] = False
            it["vibe_signal"] = "description-signal"

    vibe = [i for i in items if not i["contrast"]]
    contrast = [i for i in items if i["contrast"]]
    print(f"total {len(items)}: vibe {len(vibe)}, contrast {len(contrast)}")

    OUT.write_text(json.dumps({"vibe": vibe, "contrast": contrast}, indent=1, ensure_ascii=False))
    print("->", OUT)


if __name__ == "__main__":
    main()
