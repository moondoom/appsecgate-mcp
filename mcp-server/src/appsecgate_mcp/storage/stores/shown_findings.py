"""ShownFindingsStore — журнал находок, показанных разработчику (shown_findings.db)."""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.models.finding import Finding
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores._time import _now


class ShownFindingsStore:
    """Журнал находок, показанных разработчику (arch §3.5).

    Привязан к одному ``project_id``: каждая запись несёт проектную ось.
    Схема «воссоздаётся с нуля», если существующая таблица не содержит
    ``project_id`` (No-migration, см. AGENTS.md).
    """

    def __init__(self, db: Database, project_id: str) -> None:
        self.db = db
        self.project_id = project_id

    def _table_columns(self, table: str) -> set[str]:
        rows = self.db._fetchall(f"PRAGMA table_info({table})")
        return {r["name"] for r in rows}

    def init_schema(self) -> None:
        columns = self._table_columns("shown_findings")
        if columns and "project_id" not in columns:
            # Старая схема (без проектной оси) — пересоздаём, не мигрируем.
            self.db._execute_ddl("DROP TABLE shown_findings")
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS shown_findings (
                fingerprint TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                severity TEXT NOT NULL,
                scanner TEXT NOT NULL,
                logical_id TEXT,
                first_shown_at TIMESTAMP NOT NULL,
                last_shown_at TIMESTAMP NOT NULL,
                status_updated_at TIMESTAMP,
                show_count INTEGER DEFAULT 1,
                status TEXT NOT NULL,
                fixed_at TIMESTAMP,
                suppressed_at TIMESTAMP,
                suppress_reason TEXT,
                wont_fix_at TIMESTAMP,
                wont_fix_reason TEXT
            );
            """
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_shown_file ON shown_findings(file_path)"
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_shown_status ON shown_findings(status)"
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_shown_project ON shown_findings(project_id)"
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_shown_logical ON shown_findings(logical_id)"
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_shown_rule_file ON shown_findings(project_id, rule_id, file_path)"
        )

    async def record_shown(self, finding: Finding, logical_id: str | None = None) -> None:
        now = _now()
        await self.db.execute(
            """
            INSERT INTO shown_findings (fingerprint, project_id, rule_id, file_path, severity, scanner,
                                        logical_id,
                                        first_shown_at, last_shown_at, status_updated_at, show_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'SHOWN')
            ON CONFLICT(fingerprint) DO UPDATE SET
                logical_id = COALESCE(excluded.logical_id, shown_findings.logical_id),
                last_shown_at = excluded.last_shown_at,
                status_updated_at = excluded.status_updated_at,
                show_count = show_count + 1
            """,
            (
                finding.fingerprint,
                self.project_id,
                finding.rule_id,
                finding.file_path,
                finding.severity.value,
                finding.scanner,
                logical_id,
                now,
                now,
                now,
            ),
        )

    async def record_shown_batch(
        self,
        findings: list[Finding],
        logical_ids: dict[str, str] | None = None,
    ) -> None:
        now = _now()
        logical_ids = logical_ids or {}
        rows = [
            (
                f.fingerprint,
                self.project_id,
                f.rule_id,
                f.file_path,
                f.severity.value,
                f.scanner,
                logical_ids.get(f.fingerprint),
                now,
                now,
                now,
            )
            for f in findings
        ]
        if not rows:
            return
        await self.db.execute_many(
            """
            INSERT INTO shown_findings (fingerprint, project_id, rule_id, file_path, severity, scanner,
                                        logical_id,
                                        first_shown_at, last_shown_at, status_updated_at, show_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'SHOWN')
            ON CONFLICT(fingerprint) DO UPDATE SET
                logical_id = COALESCE(excluded.logical_id, shown_findings.logical_id),
                last_shown_at = excluded.last_shown_at,
                status_updated_at = excluded.status_updated_at,
                show_count = show_count + 1
            """,
            rows,
        )

    async def mark_fixed(self, fingerprint: str) -> None:
        now = _now()
        await self.db.execute(
            "UPDATE shown_findings SET status = 'FIXED', fixed_at = ?, status_updated_at = ? WHERE fingerprint = ?",
            (now, now, fingerprint),
        )

    async def mark_suppressed(self, fingerprint: str, reason: str) -> None:
        now = _now()
        await self.db.execute(
            """
            UPDATE shown_findings
            SET status = 'SUPPRESSED', suppressed_at = ?, suppress_reason = ?, status_updated_at = ?
            WHERE fingerprint = ?
            """,
            (now, reason, now, fingerprint),
        )

    async def was_shown(self, fingerprint: str) -> bool:
        row = await self.db.fetchone(
            "SELECT fingerprint FROM shown_findings WHERE fingerprint = ?", (fingerprint,)
        )
        return row is not None

    async def is_unresolved(self, fingerprint: str) -> bool:
        row = await self.db.fetchone(
            "SELECT status FROM shown_findings WHERE fingerprint = ?", (fingerprint,)
        )
        if row is None:
            return False
        return row["status"] not in ("FIXED", "SUPPRESSED")

    async def purge_stale_shown(
        self,
        *,
        cutoff: str,
    ) -> int:
        """Удаляет показанные находки, неактивные дольше ``cutoff`` (ISO).

        Удаляются только строки со статусом ``SHOWN``, у которых ``last_shown_at``
        старше ``cutoff``. ``finding_identity`` и ``finding_context`` сохраняются
        для детекта рецидивов (arch §4.7 Retention policy). Возвращает число
        удалённых строк.
        """
        cursor_count = await self.db.execute_rowcount(
            "DELETE FROM shown_findings WHERE status = 'SHOWN' AND last_shown_at < ?",
            (cutoff,),
        )
        return cursor_count

    async def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM shown_findings ORDER BY last_shown_at DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    async def get_by_file(self, file_path: str) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM shown_findings WHERE file_path = ? ORDER BY last_shown_at DESC",
            (file_path,),
        )
        return [dict(row) for row in rows]

    async def find(self, finding_id: str) -> dict[str, Any] | None:
        """Ищет показанную находку по fingerprint (в первую очередь) или по logical_id."""
        row = await self.db.fetchone(
            "SELECT * FROM shown_findings WHERE fingerprint = ? OR logical_id = ? LIMIT 1",
            (finding_id, finding_id),
        )
        return dict(row) if row else None

    async def set_status(
        self,
        fingerprint: str,
        status: str,
        *,
        reason: str | None = None,
    ) -> None:
        """Переводит находку в статус верификации с заполнением временной метки.

        ``status`` ∈ ``FIXED`` | ``WONT_FIX``. Метка пишется в ``fixed_at``
        либо ``wont_fix_at`` соответственно, ``status_updated_at`` — всегда.
        """
        now = _now()
        if status == "FIXED":
            await self.db.execute(
                "UPDATE shown_findings SET status='FIXED', fixed_at=?, status_updated_at=? "
                "WHERE fingerprint=?",
                (now, now, fingerprint),
            )
        elif status == "WONT_FIX":
            await self.db.execute(
                "UPDATE shown_findings SET status='WONT_FIX', wont_fix_at=?, "
                "wont_fix_reason=?, status_updated_at=? WHERE fingerprint=?",
                (now, reason or "", now, fingerprint),
            )
        else:
            raise ValueError(f"unsupported verification status: {status}")
