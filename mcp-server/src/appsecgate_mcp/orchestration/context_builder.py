"""ContextBuilder — собирает ContextPack находки (arch §4.5, §4.4 CONTEXT).

Работает по уже сохранённым (redacted) данным из ``finding_context``: чтение
исходника из ``project_root`` нужно только для окна кода вокруг находки.
Никаких секретов наружу — snippet в pack уже замаскирован при записи.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from appsecgate_mcp.models.context import (
    CodeWindow,
    ContextPack,
    ProjectRef,
    ProjectSignals,
    RuleDoc,
    SCAData,
)
from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.storage.stores import FindingContextStore

# Окно кода вокруг находки (строк) в обе стороны.
_WINDOW_RADIUS = 15

_LANG_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".sh": "shell",
    ".bash": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".tf": "hcl",
    ".toml": "toml",
}

# Ключи метаданных пакета у разных сканеров.
_PKG_KEYS = ("package", "pkg_name", "pkg_id", "name", "package_name")
_VERSION_KEYS = ("installed_version", "version", "current_version")
_FIXED_KEYS = ("fixed_version", "fixed", "patched_version")


def _detect_language(file_path: str) -> str:
    name = Path(file_path).name.lower()
    if name == "dockerfile":
        return "dockerfile"
    return _LANG_BY_EXT.get(Path(file_path).suffix.lower(), "")


def _build_window(source: str, file_path: str, line_start: int, line_end: int) -> CodeWindow | None:
    if not source:
        return None
    lines = source.splitlines()
    if not lines:
        return None
    start = max(1, line_start - _WINDOW_RADIUS)
    end = min(len(lines), line_end + _WINDOW_RADIUS)
    formatted = [f"{i:>4} │ {lines[i - 1]}" for i in range(start, end + 1)]
    return CodeWindow(
        file_path=file_path,
        language=_detect_language(file_path),
        start_line=start,
        end_line=end,
        lines=formatted,
        finding_lines=(line_start, line_end),
    )


def _parse_metadata(metadata_json: str | None) -> dict[str, Any]:
    if not metadata_json:
        return {}
    try:
        value = json.loads(metadata_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _build_sca_data(metadata: dict[str, Any]) -> SCAData | None:
    package = next((metadata.get(k) for k in _PKG_KEYS if metadata.get(k)), "")
    if not package:
        return None
    installed = next((str(metadata.get(k)) for k in _VERSION_KEYS if metadata.get(k)), "")
    fixed = next((metadata.get(k) for k in _FIXED_KEYS if metadata.get(k)), None)
    manifests = metadata.get("manifest_files") or metadata.get("manifest")
    manifest_files = (
        list(manifests) if isinstance(manifests, list) else [str(manifests)] if manifests else []
    )
    return SCAData(
        package=str(package),
        installed_version=installed,
        fixed_version=str(fixed) if fixed is not None else None,
        manifest_files=manifest_files,
    )


def _rule_doc(finding: Finding) -> RuleDoc:
    return RuleDoc(
        rule_id=finding.rule_id,
        scanner=finding.scanner,
        category=finding.category.value,
        remediation=finding.remediation,
    )


_INSTRUCTIONS = (
    "Fix the finding described below. The snippet is redacted where secrets "
    "were detected; do not attempt to recover redacted values. Scope edits to "
    "the reported file only."
)


class ContextBuilder:
    """Собирает ContextPack из finding_context + исходника проекта."""

    def __init__(
        self,
        context_store: FindingContextStore,
        *,
        project_root: str | None,
        project_id: str | None,
        project_alias: str | None = None,
        feedback_store=None,
    ) -> None:
        self.context_store = context_store
        self.project_root = Path(project_root).resolve() if project_root else None
        self.project_id = project_id or ""
        self.project_alias = project_alias or ""
        self.feedback_store = feedback_store

    async def _read_source(self, file_path: str) -> str:
        if not file_path or self.project_root is None:
            return ""
        candidate = Path(file_path)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(self.project_root)
            except ValueError:
                return ""
        target = self.project_root / candidate
        try:
            if target.is_file():
                return target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return ""

    async def build(self, finding_id: str) -> ContextPack | None:
        """Собирает контекст для находки по её fingerprint (finding_id)."""
        if self.project_id is None:
            return None
        row = await self.context_store.get(self.project_id, finding_id)
        if row is None:
            return None
        if row.get("category") == Category.LICENSE.value:
            # license-находки не попадают в ContextPack (политика §4.9).
            return None

        finding = Finding(
            fingerprint=row["fingerprint"],
            rule_id=row["rule_id"],
            severity=Severity(row["severity"]),
            file_path=row["file_path"],
            line_start=int(row.get("line_start") or 1),
            line_end=int(row.get("line_end") or 1),
            message=row.get("message") or "",
            scanner=row["scanner"],
            category=Category(row["category"]),
            snippet=row.get("snippet") or "",
            metadata={},
            remediation=row.get("remediation"),
        )
        metadata = _parse_metadata(row.get("metadata_json"))

        source = await self._read_source(finding.file_path)
        window = _build_window(source, finding.file_path, finding.line_start, finding.line_end)

        sca = _build_sca_data(metadata) if finding.category is Category.SCA else None

        signals = ProjectSignals()
        if self.feedback_store is not None:
            try:
                signals.feedback_history = await self.feedback_store.get_for(finding_id)
            except Exception:
                pass

        return ContextPack(
            project=ProjectRef(project_id=self.project_id, project_alias=self.project_alias),
            finding=finding,
            window=window,
            rule=_rule_doc(finding),
            sca=sca,
            signals=signals,
            instructions=_INSTRUCTIONS,
            output_schema={"status": "fixed", "note": "string"},
            redacted=finding.snippet == "[REDACTED]" or finding.category is Category.SECRET,
            prompt_version="v1",
        )
