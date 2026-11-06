#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPOS = ROOT / "repos"
OUT = ROOT / "artifacts" / "agent300-manifest.json"
LANGS = {"python", "javascript", "typescript", "go", "ruby", "php", "java"}
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
    "vibe cod",
    "built with claude",
    "built with cursor",
    "written by ai",
    "100% ai",
    "ai-generated",
    "coded by claude",
    "built entirely with ai",
    "claude code",
    "vibecod",
)


def search(query: str) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "per_page": 100, "sort": "stars"})
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "appsecgate-agent-corpus"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/search/repositories?{params}", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response).get("items", [])
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub search failed with HTTP {exc.code}: {query}") from exc


def normalize(item: dict, *, contrast: bool, signal: str | None) -> dict:
    return {
        "name": item["name"],
        "full_name": item["full_name"],
        "url": item["html_url"],
        "clone_url": item["clone_url"],
        "stars": item["stargazers_count"],
        "lang": (item.get("language") or "").lower(),
        "pushed_at": item["pushed_at"],
        "description": item.get("description") or "",
        "vibe_signal": signal,
        "contrast": contrast,
    }


def candidates() -> dict[bool, list[dict]]:
    shortlist = json.loads((ROOT / "artifacts" / "vibe100-shortlist.json").read_text())
    pools = {False: list(shortlist["vibe"]), True: list(shortlist["contrast"])}
    seen = {item["full_name"] for values in pools.values() for item in values}
    for contrast, queries in ((False, VIBE_QUERIES), (True, CONTRAST_QUERIES)):
        for query in queries:
            for raw in search(query):
                if raw["full_name"] in seen:
                    continue
                description = (raw.get("description") or "").lower()
                is_contrast = contrast and not any(signal in description for signal in AI_SIGNALS)
                item = normalize(
                    raw,
                    contrast=is_contrast,
                    signal=None if is_contrast else query.split(" in:")[0],
                )
                if item["lang"] not in LANGS:
                    continue
                pools[item["contrast"]].append(item)
                seen.add(item["full_name"])
            time.sleep(7)
    for values in pools.values():
        values.sort(key=lambda item: (-item["stars"], item["full_name"]))
    return pools


def git_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()


def remote_sha(item: dict) -> str:
    result = subprocess.run(
        ["git", "ls-remote", item["clone_url"], "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout.split()[0]


def clone_repo(item: dict, repo: Path) -> str:
    if (repo / ".git").exists():
        return git_sha(repo)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", "--no-tags",
             item["clone_url"], str(repo)],
            check=True,
            timeout=180,
        )
        return git_sha(repo)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        if repo.exists():
            shutil.rmtree(repo)
        sha = remote_sha(item)
        archive = repo.with_suffix(".tar.gz")
        with urllib.request.urlopen(
            f"https://codeload.github.com/{item['full_name']}/tar.gz/{sha}", timeout=120
        ) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with tarfile.open(archive) as bundle:
            bundle.extractall(repo.parent)
        extracted = next(repo.parent.glob(f"*-{sha[:7]}"))
        extracted.rename(repo)
        archive.unlink()
        return sha


def main() -> None:
    existing = json.loads((ROOT / "artifacts" / "vibe100-final.json").read_text())
    existing_names = {item["name"] for item in existing}
    pools = candidates()
    selected = list(existing)
    for contrast, target in ((False, 140), (True, 60)):
        fresh = [item for item in pools[contrast] if item["name"] not in existing_names]
        if len(fresh) < target:
            raise SystemExit(
                f"not enough new repositories for contrast={contrast}: {len(fresh)} < {target}"
            )
        selected.extend(fresh[:target])
    if len(selected) != 300:
        raise SystemExit(f"expected 300 repositories, got {len(selected)}")

    import concurrent.futures

    workers = int(os.environ.get("CORPUS_CLONE_WORKERS", "8"))

    def fetch(item: dict) -> dict:
        repo = REPOS / item["name"]
        return {**item, "development": item["name"] in existing_names, "sha": clone_repo(item, repo)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        manifest = list(pool.map(fetch, selected))
    OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    summary = {
        "total": len(manifest),
        "development": sum(item["development"] for item in manifest),
        "held_out": sum(not item["development"] for item in manifest),
        "vibe": sum(not item["contrast"] for item in manifest),
        "contrast": sum(item["contrast"] for item in manifest),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
