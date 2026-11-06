"""Host-side загрузка внешних Semgrep-правил в user overlay."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

PROVENANCE_NAME = ".external-rules.json"


@dataclass(frozen=True)
class RuleSource:
    name: str
    repository: str
    revision: str
    license: str
    redistribution: str
    language_dirs: dict[str, tuple[str, ...]]
    common_dirs: tuple[str, ...]

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repository}/archive/{self.revision}.tar.gz"

    @property
    def bundle_id(self) -> str:
        return f"external/{self.name}"


SOURCES = {
    "semgrep": RuleSource(
        name="semgrep",
        repository="semgrep/semgrep-rules",
        revision="16b9e6d45f10649f6a531ec4838ed9924372c3bc",
        license="Semgrep-Rules-1.0",
        redistribution="restricted",
        language_dirs={
            "python": ("python",),
            "javascript": ("javascript",),
            "typescript": ("typescript",),
            "go": ("go",),
            "java": ("java",),
            "ruby": ("ruby",),
            "php": ("php",),
            "c": ("c",),
            "csharp": ("csharp",),
            "rust": ("rust",),
            "swift": ("swift",),
        },
        common_dirs=("generic", "json", "yaml", "dockerfile", "terraform"),
    ),
    "trailofbits": RuleSource(
        name="trailofbits",
        repository="trailofbits/semgrep-rules",
        revision="31390b3a99c04c81522d1b37c8d1900aa2dd4094",
        license="AGPL-3.0-only",
        redistribution="restricted",
        language_dirs={
            "python": ("python",),
            "javascript": ("javascript",),
            "go": ("go",),
            "java": ("jvm",),
            "ruby": ("ruby",),
            "rust": ("rs",),
            "swift": ("swift",),
        },
        common_dirs=("generic", "yaml", "hcl/terraform"),
    ),
}

PROFILES = {
    "agent300": ("python", "javascript", "typescript", "go", "java", "ruby", "php"),
}


class RulesFetchError(RuntimeError):
    pass


def available_languages() -> list[str]:
    return sorted({lang for source in SOURCES.values() for lang in source.language_dirs})


def selected_dirs(source: RuleSource, languages: list[str]) -> list[str]:
    unknown = sorted(set(languages) - set(source.language_dirs))
    dirs = list(source.common_dirs)
    for language in languages:
        dirs.extend(source.language_dirs.get(language, ()))
    return sorted(set(dirs)), unknown


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _load_manifest(rules_dir: Path) -> dict[str, Any]:
    path = rules_dir / "manifest.yaml"
    if not path.exists():
        return {"version": "1.0.0", "distribution_mode": "commercial", "bundles": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("bundles", []), list):
        raise RulesFetchError(f"invalid user rules manifest: {path}")
    data.setdefault("version", "1.0.0")
    data.setdefault("distribution_mode", "commercial")
    data.setdefault("bundles", [])
    return data


def _save_manifest(rules_dir: Path, manifest: dict[str, Any]) -> None:
    _atomic_write(
        rules_dir / "manifest.yaml",
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
    )


def _load_provenance(rules_dir: Path) -> dict[str, Any]:
    path = rules_dir / PROVENANCE_NAME
    if not path.exists():
        return {"version": 1, "sources": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _download(source: RuleSource, cache_dir: Path) -> tuple[Path, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / f"{source.name}-{source.revision}.tar.gz"
    digest_path = archive.with_suffix(archive.suffix + ".sha256")
    if archive.exists() and digest_path.exists():
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest == digest_path.read_text(encoding="utf-8").strip():
            return archive, digest
    temporary = archive.with_suffix(".download")
    digest = hashlib.sha256()
    try:
        with (
            urllib.request.urlopen(source.url, timeout=60) as response,
            temporary.open("wb") as out,
        ):
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                out.write(chunk)
        os.replace(temporary, archive)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise RulesFetchError(f"failed to download {source.url}: {exc}") from exc
    value = digest.hexdigest()
    digest_path.write_text(value + "\n", encoding="utf-8")
    return archive, value


def _selected_members(archive: Path, directories: list[str]) -> list[tuple[tarfile.TarInfo, str]]:
    selected: list[tuple[tarfile.TarInfo, str]] = []
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            path = PurePosixPath(member.name)
            if len(path.parts) < 2:
                continue
            relative = PurePosixPath(*path.parts[1:])
            if relative.is_absolute() or ".." in relative.parts:
                raise RulesFetchError(f"unsafe archive path: {member.name}")
            if any(
                relative == PurePosixPath(directory) or PurePosixPath(directory) in relative.parents
                for directory in directories
            ):
                is_rule = relative.suffix.lower() in {".yaml", ".yml"}
                is_fixture = ".test." in relative.name or "tests" in relative.parts
                if member.isfile() and is_rule and not is_fixture:
                    selected.append((member, str(relative)))
    return selected


def _extract_source(
    archive: Path, destination: Path, directories: list[str], seen_ids: set[str]
) -> tuple[int, list[dict[str, Any]]]:
    duplicates: list[dict[str, Any]] = []
    count = 0
    with tarfile.open(archive, "r:gz") as bundle:
        members = _selected_members(archive, directories)
        if not members:
            raise RulesFetchError(f"no YAML rules selected in {archive.name}")
        for member, relative in members:
            extracted = bundle.extractfile(member)
            if extracted is None:
                continue
            content = extracted.read()
            try:
                document = yaml.safe_load(content) or {}
                ids = [str(rule["id"]) for rule in document.get("rules", []) if "id" in rule]
            except (yaml.YAMLError, TypeError, AttributeError) as exc:
                raise RulesFetchError(f"invalid rule file {relative}: {exc}") from exc
            duplicate_ids = sorted(set(ids) & seen_ids)
            if duplicate_ids:
                duplicates.append({"file": relative, "rule_ids": duplicate_ids})
                continue
            seen_ids.update(ids)
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
            count += 1
        root_name = bundle.getmembers()[0].name.split("/")[0]
        try:
            license_file = bundle.extractfile(f"{root_name}/LICENSE")
        except KeyError:
            license_file = None
        if license_file is not None:
            (destination / "LICENSE").write_bytes(license_file.read())
    return count, duplicates


def _install_directory(rules_dir: Path, source: RuleSource) -> Path:
    return rules_dir / f"external-{source.name}"


def _ruleset_hash(rules_dir: Path, names: list[str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(names):
        root = rules_dir / f"external-{name}"
        for path in sorted(root.rglob("*.y*ml")):
            digest.update(str(path.relative_to(rules_dir)).encode("utf-8"))
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return f"sha256:{digest.hexdigest()}"


def install_rules(
    data_dir: Path, names: list[str], languages: list[str], *, accept_licenses: bool
) -> dict[str, Any]:
    if not accept_licenses:
        raise RulesFetchError("external rules require --accept-licenses; review `rules list` first")
    unknown_sources = sorted(set(names) - set(SOURCES))
    if unknown_sources:
        raise RulesFetchError(f"unknown sources: {', '.join(unknown_sources)}")
    unknown_languages = sorted(set(languages) - set(available_languages()))
    if unknown_languages:
        raise RulesFetchError(f"unknown languages: {', '.join(unknown_languages)}")
    rules_dir = data_dir / "rules"
    provenance = _load_provenance(rules_dir)
    manifest = _load_manifest(rules_dir)
    requested = sorted(set(names))
    previous = provenance.get("sources", {})
    if set(previous) == set(requested) and all(
        previous[name].get("languages") == languages for name in requested
    ):
        return provenance

    staging = data_dir / ".rules-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    seen_ids: set[str] = set()
    try:
        for name in requested:
            source = SOURCES[name]
            directories, skipped = selected_dirs(source, languages)
            archive, archive_hash = _download(source, data_dir / "cache" / "external-rules")
            destination = staging / f"external-{name}"
            destination.mkdir()
            count, duplicates = _extract_source(archive, destination, directories, seen_ids)
            target = _install_directory(rules_dir, source)
            if target.exists():
                shutil.rmtree(target)
            rules_dir.mkdir(parents=True, exist_ok=True)
            os.replace(destination, target)
            previous[name] = {
                "repository": source.repository,
                "revision": source.revision,
                "license": source.license,
                "archive_sha256": archive_hash,
                "languages": languages,
                "directories": directories,
                "unsupported_languages": skipped,
                "rule_files": count,
                "duplicates": duplicates,
            }
        provenance["sources"] = {name: previous[name] for name in requested}
        provenance["languages"] = languages
        provenance["ruleset_hash"] = _ruleset_hash(rules_dir, requested)
        managed_ids = {SOURCES[name].bundle_id for name in SOURCES}
        bundles = [b for b in manifest["bundles"] if b.get("id") not in managed_ids]
        for name in requested:
            source = SOURCES[name]
            bundles.append(
                {
                    "id": source.bundle_id,
                    "scanner": "semgrep",
                    "path": f"/opt/appsecgate/rules/external-{name}",
                    "license": source.license,
                    "source": f"https://github.com/{source.repository}/tree/{source.revision}",
                    "redistribution": source.redistribution,
                    "tags": ["external", *languages],
                }
            )
        manifest["bundles"] = bundles
        _save_manifest(rules_dir, manifest)
        _atomic_write(
            rules_dir / PROVENANCE_NAME,
            json.dumps(provenance, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return provenance


def remove_rules(data_dir: Path, names: list[str]) -> dict[str, Any]:
    unknown = sorted(set(names) - set(SOURCES))
    if unknown:
        raise RulesFetchError(f"unknown sources: {', '.join(unknown)}")
    rules_dir = data_dir / "rules"
    provenance = _load_provenance(rules_dir)
    manifest = _load_manifest(rules_dir)
    for name in names:
        shutil.rmtree(rules_dir / f"external-{name}", ignore_errors=True)
        provenance.get("sources", {}).pop(name, None)
    removed_ids = {SOURCES[name].bundle_id for name in names}
    manifest["bundles"] = [b for b in manifest["bundles"] if b.get("id") not in removed_ids]
    remaining = sorted(provenance.get("sources", {}))
    provenance["ruleset_hash"] = _ruleset_hash(rules_dir, remaining)
    _save_manifest(rules_dir, manifest)
    _atomic_write(
        rules_dir / PROVENANCE_NAME,
        json.dumps(provenance, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
    return provenance
