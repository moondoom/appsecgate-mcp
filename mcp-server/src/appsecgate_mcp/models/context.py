"""Модели контекста находки для fix-workflow (arch §4.5).

``ContextPack`` — то, что ``get_fix_context`` возвращает агенту: redacted
finding, окно кода, документация правила и (для SCA) данные пакета.
Собирается ``ContextBuilder``'ом уже после redaction при записи.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from appsecgate_mcp.models.finding import Finding


class ProjectRef(BaseModel):
    """Ссылка на проект (project_id + alias), arch §4.5."""

    project_id: str
    project_alias: str = ""


class CodeWindow(BaseModel):
    """Окно кода вокруг находки с проставленными номерами строк."""

    file_path: str
    language: str = ""
    start_line: int
    end_line: int
    lines: list[str] = Field(default_factory=list)
    finding_lines: tuple[int, int] = (1, 1)


class RuleDoc(BaseModel):
    """Документация правила, которым найдена проблема."""

    rule_id: str
    scanner: str = ""
    category: str = ""
    cwe: list[str] = Field(default_factory=list)
    owasp: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    remediation: str | None = None
    known_patch: str | None = None
    confidence: str | None = None


class SCAData(BaseModel):
    """Данные уязвимого пакета для SCA-находок."""

    package: str
    installed_version: str
    fixed_version: str | None = None
    manifest_files: list[str] = Field(default_factory=list)


class ProjectSignals(BaseModel):
    """Дополнительные сигналы проекта для LLM-агента."""

    git_diff: str = ""
    feedback_history: list[dict[str, Any]] = Field(default_factory=list)
    is_test_file: bool = False
    related_findings: list[str] = Field(default_factory=list)


class ContextPack(BaseModel):
    """Полный контекст находки (arch §4.5). Snippet уже redacted."""

    project: ProjectRef
    finding: Finding
    window: CodeWindow | None = None
    rule: RuleDoc
    sca: SCAData | None = None
    signals: ProjectSignals = Field(default_factory=ProjectSignals)
    instructions: str = ""
    output_schema: dict[str, Any] = Field(default_factory=dict)
    redacted: bool = False
    prompt_version: str = "v1"
