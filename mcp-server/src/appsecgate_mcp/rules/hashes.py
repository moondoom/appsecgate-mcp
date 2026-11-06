from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from appsecgate_mcp.rules.resolver import ResolvedBundle


def _definitions(path: Path, scanner: str) -> list[dict[str, Any]]:
    try:
        if scanner == "semgrep":
            documents = yaml.safe_load_all(path.read_text(encoding="utf-8"))
            return [
                rule
                for document in documents
                if isinstance(document, dict)
                for rule in document.get("rules", [])
                if isinstance(rule, dict) and isinstance(rule.get("id"), str)
            ]
        if scanner == "gitleaks":
            document = tomllib.loads(path.read_text(encoding="utf-8"))
            return [
                rule
                for rule in document.get("rules", [])
                if isinstance(rule, dict) and isinstance(rule.get("id"), str)
            ]
    except (OSError, UnicodeError, yaml.YAMLError, tomllib.TOMLDecodeError):
        return []
    return []


def _definition_hash(definition: dict[str, Any]) -> str:
    canonical = json.dumps(
        definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def compute_rule_hashes(bundles: list[ResolvedBundle]) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for bundle in bundles:
        scanner = bundle.scanner.lower()
        if scanner not in {"semgrep", "gitleaks"}:
            continue
        for filename in bundle.files:
            for definition in _definitions(Path(filename), scanner):
                key = f"{scanner}:{definition['id']}"
                digest = _definition_hash(definition)
                if key in hashes and hashes[key] != digest:
                    hashes[key] = None
                else:
                    hashes[key] = digest
    return hashes
