#!/usr/bin/env python3
"""Добор contributors через GitHub API (per_page=1 + Link:last), уважает rate-limit."""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FINAL_PATH = ROOT / "artifacts" / "vibe100-final.json"


def contrib_count(full_name: str) -> tuple[int | None, int]:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{full_name}/contributors?per_page=1&anon=true",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "appsecgate-tp0001"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        link = r.headers.get("Link", "")
        remaining = int(r.headers.get("X-RateLimit-Remaining", "0"))
        items = json.load(r)
    m = re.search(r'page=(\d+)>; rel="last"', link)
    if m:
        return int(m.group(1)), remaining
    return (len(items) if isinstance(items, list) else None), remaining


def main() -> None:
    data = json.loads(FINAL_PATH.read_text())
    done = skipped = 0
    for it in data:
        if it.get("contributors"):
            skipped = True
            continue
        try:
            n, remaining = contrib_count(it["full_name"])
        except urllib.error.HTTPError as e:
            print("HTTP", e.code, it["full_name"])
            break
        it["contributors"] = n
        done += 1
        if remaining <= 1:
            print("rate limit, стоп. сделано:", done)
            break
        time.sleep(0.3)
    FINAL_PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    missing = sum(1 for it in data if not it.get("contributors"))
    print(f"done {done}, still missing {missing}")


if __name__ == "__main__":
    main()
