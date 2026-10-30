"""FindingContextStore — персистентный контекст находки."""

from __future__ import annotations

import json
from typing import Any

from appsecgate_mcp.models.finding import Finding
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores._time import _now


class FindingContextStore:
    """Персистентный контекст находки (arch §4.7).

    Хранит (уже redacted) полную находку для страницы/ContextPack. Данные
    пишутся после ``Redactor`` — см. инвариант №4 в AGENTS.md. Дополнен
    полями ``severity``/``scanner``/``category``/``line_*``, чтобы
    ``ContextBuilder`` мог воссоздать ``Finding`` и окно кода без перескана.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS finding_context (
                fingerprint      TEXT NOT NULL,
                project_id       TEXT NOT NULL,
                logical_id       TEXT NOT NULL,
                rule_id          TEXT NOT NULL,
                file_path        TEXT NOT NULL,
                severity         TEXT NOT NULL,
                scanner          TEXT NOT NULL,
                category         TEXT NOT NULL,
                line_start       INTEGER NOT NULL,
                line_end         INTEGER NOT NULL,
                snippet          TEXT,
                message          TEXT,
                metadata_json    TEXT,
                remediation      TEXT,
                scanner_version  TEXT,
                captured_at      TIMESTAMP NOT NULL,
                PRIMARY KEY (project_id, fingerprint)
            );
            """
        )

    async def upsert(self, project_id: str, logical_id: str, finding: Finding) -> None:
        """Пишет уже redacted ``finding`` (snippet/message/metadata маскированы)."""
        now = _now()
        await self.db.execute(
            """
            INSERT INTO finding_context
                (fingerprint, project_id, logical_id, rule_id, file_path,
                 severity, scanner, category, line_start, line_end,
                 snippet, message, metadata_json, remediation, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, fingerprint) DO UPDATE SET
                logical_id   = excluded.logical_id,
                severity     = excluded.severity,
                scanner      = excluded.scanner,
                category     = excluded.category,
                line_start   = excluded.line_start,
                line_end     = excluded.line_end,
                snippet      = excluded.snippet,
                message      = excluded.message,
                metadata_json = excluded.metadata_json,
                remediation  = excluded.remediation,
                captured_at  = excluded.captured_at
            """,
            (
                finding.fingerprint,
                project_id,
                logical_id,
                finding.rule_id,
                finding.file_path,
                finding.severity.value,
                finding.scanner,
                finding.category.value,
                finding.line_start,
                finding.line_end,
                finding.snippet,
                finding.message,
                json.dumps(finding.metadata, sort_keys=True, default=str),
                finding.remediation,
                now,
            ),
        )

    async def get(self, project_id: str, fingerprint: str) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            "SELECT * FROM finding_context WHERE project_id = ? AND fingerprint = ?",
            (project_id, fingerprint),
        )
        return dict(row) if row else None
