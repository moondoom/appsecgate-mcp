"""ShownFindingsStore — журнал находок, показанных разработчику (shown_findings.db)."""

from __future__ import annotations

from typing import Any

from appsecgate_mcp.models.finding import Finding
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores import shown_reconcile, shown_report
from appsecgate_mcp.storage.stores._time import _now


class ShownFindingsStore:
    """Журнал находок, показанных разработчику (arch §3.5).

    Привязан к одному ``project_id``; схема пересоздаётся при отсутствии
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
                fingerprint          TEXT PRIMARY KEY,
                project_id           TEXT NOT NULL,       -- T7, T9
                rule_id              TEXT NOT NULL,
                file_path            TEXT NOT NULL,
                severity             TEXT NOT NULL,
                scanner              TEXT NOT NULL,
                category             TEXT NOT NULL,

                status               TEXT NOT NULL,        -- SHOWN | POTENTIALLY_FIXED | FIXED | REOPENED | SUPPRESSED | WONT_FIX
                status_updated_at    TIMESTAMP NOT NULL,   -- аудит переходов (ADR-0005 §2.2)
                missed_scan_count    INTEGER NOT NULL DEFAULT 0,

                first_seen_branch    TEXT,                 -- ADR-0005 §2.4
                first_seen_commit    TEXT,
                last_seen_branch     TEXT,
                last_seen_commit     TEXT,

                first_shown_at       TIMESTAMP,            -- nullable: заполняется mark_shown() (К3)
                last_shown_at        TIMESTAMP,
                show_count           INTEGER NOT NULL DEFAULT 0,

                first_seen_at        TIMESTAMP NOT NULL,   -- факт обнаружения (positive-merge)
                last_seen_at         TIMESTAMP NOT NULL,
                scan_count           INTEGER NOT NULL DEFAULT 1,

                fixed_at             TIMESTAMP,
                fixed_confirmed_by   TEXT,                 -- 'verify_fix' | NULL (ADR-0005 §2.9)

                suppressed_at        TIMESTAMP,
                suppress_reason      TEXT,

                wont_fix_at          TIMESTAMP,
                wont_fix_reason      TEXT
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
            "CREATE INDEX IF NOT EXISTS idx_shown_rule_file ON shown_findings(project_id, rule_id, file_path)"
        )

    async def _upsert_identity(self, finding: Finding, logical_id: str) -> None:
        """Связка ``logical_id → fingerprint`` в ``finding_identity`` (ADR-0005 §2.8, К1).

        ``first_seen_at`` фиксируется один раз, ``last_fingerprint``/``last_seen_at`` обновляются.
        """
        now = _now()
        await self.db.execute(
            """
            INSERT INTO finding_identity
                (logical_id, project_id, rule_id, file_path, first_seen_at, last_fingerprint, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, logical_id) DO UPDATE SET
                last_fingerprint = excluded.last_fingerprint,
                last_seen_at     = excluded.last_seen_at
            """,
            (
                logical_id,
                self.project_id,
                finding.rule_id,
                finding.file_path,
                now,
                finding.fingerprint,
                now,
            ),
        )

    async def record_shown(
        self,
        finding: Finding,
        logical_id: str | None = None,
        *,
        branch: str | None = None,
        commit: str | None = None,
    ) -> None:
        """Positive-merge (ADR-0005 §2.1–2.2): фиксирует факт обнаружения.

        Пишет ``first/last_seen_*``, ``scan_count++``; ``POTENTIALLY_FIXED → SHOWN``,
        ``FIXED → REOPENED`` (К4). ``*_shown_*`` — ``mark_shown()`` (К3, PR-C).
        """
        now = _now()
        await self.db.execute(
            """
            INSERT INTO shown_findings (fingerprint, project_id, rule_id, file_path, severity, scanner, category,
                                        status, status_updated_at, missed_scan_count,
                                        first_seen_branch, first_seen_commit, last_seen_branch, last_seen_commit,
                                        first_seen_at, last_seen_at, scan_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'SHOWN', ?, 0, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(fingerprint) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                last_seen_branch = excluded.last_seen_branch,
                last_seen_commit = excluded.last_seen_commit,
                scan_count = shown_findings.scan_count + 1,
                status = CASE shown_findings.status
                    WHEN 'POTENTIALLY_FIXED' THEN 'SHOWN'
                    WHEN 'FIXED' THEN 'REOPENED'
                    ELSE shown_findings.status
                END,
                missed_scan_count = CASE
                    WHEN shown_findings.status IN ('SHOWN', 'POTENTIALLY_FIXED', 'REOPENED') THEN 0
                    ELSE shown_findings.missed_scan_count
                END,
                status_updated_at = excluded.status_updated_at
            """,
            (
                finding.fingerprint,
                self.project_id,
                finding.rule_id,
                finding.file_path,
                finding.severity.value,
                finding.scanner,
                finding.category.value,
                now,
                branch,
                commit,
                branch,
                commit,
                now,
                now,
            ),
        )
        if logical_id:
            await self._upsert_identity(finding, logical_id)

    async def record_shown_batch(
        self,
        findings: list[Finding],
        logical_ids: dict[str, str] | None = None,
        *,
        branch: str | None = None,
        commit: str | None = None,
    ) -> None:
        """Пакетный positive-merge (см. ``record_shown``) + связки logical_id → fingerprint."""
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
                f.category.value,
                now,
                branch,
                commit,
                branch,
                commit,
                now,
                now,
            )
            for f in findings
        ]
        if not rows:
            return
        await self.db.execute_many(
            """
            INSERT INTO shown_findings (fingerprint, project_id, rule_id, file_path, severity, scanner, category,
                                        status, status_updated_at, missed_scan_count,
                                        first_seen_branch, first_seen_commit, last_seen_branch, last_seen_commit,
                                        first_seen_at, last_seen_at, scan_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'SHOWN', ?, 0, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(fingerprint) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                last_seen_branch = excluded.last_seen_branch,
                last_seen_commit = excluded.last_seen_commit,
                scan_count = shown_findings.scan_count + 1,
                status = CASE shown_findings.status
                    WHEN 'POTENTIALLY_FIXED' THEN 'SHOWN'
                    WHEN 'FIXED' THEN 'REOPENED'
                    ELSE shown_findings.status
                END,
                missed_scan_count = CASE
                    WHEN shown_findings.status IN ('SHOWN', 'POTENTIALLY_FIXED', 'REOPENED') THEN 0
                    ELSE shown_findings.missed_scan_count
                END,
                status_updated_at = excluded.status_updated_at
            """,
            rows,
        )
        for f in findings:
            lid = logical_ids.get(f.fingerprint)
            if lid:
                await self._upsert_identity(f, lid)

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

    async def unsuppress(self, fingerprint: str) -> None:
        """Снимает SUPPRESSED/WONT_FIX → SHOWN (ADR-0006 §2.1, событие ``unsuppressed``).

        Эмитент — ``suppress_finding(action="unsuppress")``; маркеры
        suppression/WONT_FIX очищаются. Для остальных статусов — no-op.
        """
        now = _now()
        await self.db.execute(
            """
            UPDATE shown_findings
            SET status = 'SHOWN', suppressed_at = NULL, suppress_reason = NULL,
                wont_fix_at = NULL, wont_fix_reason = NULL, status_updated_at = ?
            WHERE fingerprint = ? AND status IN ('SUPPRESSED', 'WONT_FIX')
            """,
            (now, fingerprint),
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
        """Удаляет SHOWN-строки старше ``cutoff``; identity/context сохраняются (arch §4.7)."""
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
        """Находит показанную находку по fingerprint или logical_id (через finding_identity)."""
        row = await self.db.fetchone(
            """
            SELECT s.*, i.logical_id
            FROM shown_findings s
            LEFT JOIN finding_identity i
                ON i.project_id = s.project_id AND i.last_fingerprint = s.fingerprint
            WHERE s.fingerprint = ?
            LIMIT 1
            """,
            (finding_id,),
        )
        if row is not None:
            return dict(row)
        row = await self.db.fetchone(
            """
            SELECT s.*, i.logical_id
            FROM shown_findings s
            JOIN finding_identity i
                ON i.project_id = s.project_id AND i.last_fingerprint = s.fingerprint
            WHERE i.project_id = ? AND i.logical_id = ?
            LIMIT 1
            """,
            (self.project_id, finding_id),
        )
        return dict(row) if row else None

    async def set_status(
        self,
        fingerprint: str,
        status: str,
        *,
        reason: str | None = None,
        confirmed_by: str | None = None,
    ) -> None:
        """Переводит находку в статус верификации (ADR-0005 §2.9): FIXED | REOPENED | WONT_FIX."""
        now = _now()
        if status == "FIXED":
            await self.db.execute(
                "UPDATE shown_findings SET status='FIXED', fixed_at=?, "
                "fixed_confirmed_by=?, status_updated_at=? WHERE fingerprint=?",
                (now, confirmed_by, now, fingerprint),
            )
        elif status == "REOPENED":
            await self.db.execute(
                "UPDATE shown_findings SET status='REOPENED', status_updated_at=? "
                "WHERE fingerprint=?",
                (now, fingerprint),
            )
        elif status == "WONT_FIX":
            await self.db.execute(
                "UPDATE shown_findings SET status='WONT_FIX', wont_fix_at=?, "
                "wont_fix_reason=?, status_updated_at=? WHERE fingerprint=?",
                (now, reason or "", now, fingerprint),
            )
        else:
            raise ValueError(f"unsupported verification status: {status}")

    async def get_negative_candidates(
        self,
        project_id: str,
        file_paths: list[str] | None = None,
        branch: str | None = None,
    ) -> list[dict[str, Any]]:
        """Кандидаты на negative-merge в охвате тула (branch-фильтр §2.4, К10)."""
        return await shown_reconcile.get_negative_candidates(
            self.db, project_id, file_paths, branch
        )

    async def mark_missing(self, updates: list[tuple[str, str, int]]) -> None:
        """Применяет negative-merge переходы; не трогает терминальные статусы (К7)."""
        await shown_reconcile.mark_missing(self.db, updates)

    async def get_statuses(self, fingerprints: list[str]) -> dict[str, str]:
        """Пред-скан статусы находок (классификация new/reaffirmed/reopened, PR-C)."""
        return await shown_report.get_statuses(self.db, fingerprints)

    async def mark_shown(self, fingerprints: list[str]) -> None:
        """K3: находка реально попала в ответ агенту (ADR-0005 §2.3)."""
        await shown_report.mark_shown(self.db, fingerprints)

    async def list_potentially_fixed(
        self,
        branch: str | None,
        *,
        limit: int = 25,
    ) -> tuple[list[str], int, bool]:
        """Актуальные POTENTIALLY_FIXED проекта/ветки (§2.5, К18)."""
        return await shown_report.list_potentially_fixed(
            self.db, self.project_id, branch, limit=limit
        )
