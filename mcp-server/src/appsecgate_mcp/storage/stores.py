"""Все хранилища предметной области в одном модуле.

На Фазе 1 держим store-классы вместе: проще навигировать и править.
Отдельные файлы появятся при росте (Фаза 2), если понадобятся.

Хранилища:
  * ProjectsStore        — реестр проектов (projects)
  * FindingIdentityStore — стабильная идентичность находки
  * FindingContextStore  — персистентный контекст находки
  * ShownFindingsStore   — журнал показанных находок (shown_findings.db)
  * FeedbackStore        — обратная связь разработчика (feedback.db)
  * SuppressionStore     — локальные suppression
  * ScanCacheStore       — кэш результатов сканирования (минимальный, возможно уйдёт)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from appsecgate_mcp.models.finding import Finding, Suppression
from appsecgate_mcp.storage.db import Database


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
        now = _now_iso()
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
        now = _now_iso()
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
        now = _now_iso()
        await self.db.execute(
            "UPDATE shown_findings SET status = 'FIXED', fixed_at = ?, status_updated_at = ? WHERE fingerprint = ?",
            (now, now, fingerprint),
        )

    async def mark_suppressed(self, fingerprint: str, reason: str) -> None:
        now = _now_iso()
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
        now = _now_iso()
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


class FixAttemptsStore:
    """Журнал попыток верификации находок (arch §4.7).

    Каждая попытка — одна ``verify_fix``/``verify_fix_batch`` запись: что
    агент заявил (``reported_status``) и что подтвердил перескан сервера
    (``verified_status``). Собственный ``attempt_num`` на ``logical_id``.
    """

    _STATUSES = ("FIXED", "NOT_FIXED", "WONT_FIX")

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS fix_attempts (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id         TEXT NOT NULL,
                logical_id         TEXT NOT NULL,
                fingerprint        TEXT NOT NULL,
                rule_id            TEXT NOT NULL,
                file_path          TEXT NOT NULL,
                attempt_num        INTEGER NOT NULL,
                reported_status    TEXT NOT NULL,
                verified_status    TEXT NOT NULL,
                note               TEXT,
                session_id         TEXT NOT NULL,
                agent_reported_at  TIMESTAMP NOT NULL,
                verified_at        TIMESTAMP NOT NULL
            );
            """
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_fix_attempts_project "
            "ON fix_attempts(project_id, logical_id)"
        )

    async def next_attempt_num(self, project_id: str, logical_id: str) -> int:
        row = await self.db.fetchone(
            "SELECT MAX(attempt_num) AS n FROM fix_attempts WHERE project_id=? AND logical_id=?",
            (project_id, logical_id),
        )
        return int(row["n"]) + 1 if row and row["n"] is not None else 1

    async def record(
        self,
        *,
        project_id: str,
        logical_id: str,
        fingerprint: str,
        rule_id: str,
        file_path: str,
        reported_status: str,
        verified_status: str,
        note: str | None,
        session_id: str,
    ) -> int:
        """Пишет запись об attempt; возвращает attempt_num (id последней записи)."""
        attempt_num = await self.next_attempt_num(project_id, logical_id)
        now = _now_iso()
        await self.db.execute(
            """
            INSERT INTO fix_attempts
                (project_id, logical_id, fingerprint, rule_id, file_path, attempt_num,
                 reported_status, verified_status, note, session_id,
                 agent_reported_at, verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                logical_id,
                fingerprint,
                rule_id,
                file_path,
                attempt_num,
                reported_status,
                verified_status,
                note or "",
                session_id,
                now,
                now,
            ),
        )
        return attempt_num

    async def list_for(self, project_id: str, finding_id: str) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM fix_attempts WHERE project_id=? AND (fingerprint=? OR logical_id=?) "
            "ORDER BY verified_at DESC",
            (project_id, finding_id, finding_id),
        )
        return [dict(row) for row in rows]

    async def coverage(self, project_id: str) -> dict[str, int]:
        """Число уникальных ``logical_id`` с попытками и общее число уникальных находок."""
        row = await self.db.fetchone(
            "SELECT COUNT(DISTINCT logical_id) AS n FROM fix_attempts WHERE project_id=?",
            (project_id,),
        )
        attempts = int(row["n"]) if row and row["n"] is not None else 0
        total_row = await self.db.fetchone(
            "SELECT COUNT(DISTINCT logical_id) AS n FROM shown_findings WHERE project_id=?",
            (project_id,),
        )
        total = int(total_row["n"]) if total_row and total_row["n"] is not None else 0
        return {"attempts": attempts, "total": total}


class FeedbackStore:
    """Обратная связь разработчика — офлайн-очередь для master (Фаза 2)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                feedback_type TEXT NOT NULL,  -- FALSE_POSITIVE | CONFIRMED | WONT_FIX
                reason TEXT,
                created_at TIMESTAMP NOT NULL,
                synced_at TIMESTAMP
            );
            """
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_feedback_fingerprint ON feedback(fingerprint)"
        )

    async def save(self, fingerprint: str, feedback_type: str, reason: str | None = None) -> int:
        normalized = feedback_type.strip().upper()
        if normalized not in ("FALSE_POSITIVE", "CONFIRMED", "WONT_FIX"):
            raise ValueError(f"Invalid feedback_type: {feedback_type}")
        await self.db.execute(
            "INSERT INTO feedback (fingerprint, feedback_type, reason, created_at) VALUES (?, ?, ?, ?)",
            (fingerprint, normalized, reason or "", _now_iso()),
        )
        row = await self.db.fetchone("SELECT last_insert_rowid() AS id")
        return int(row["id"]) if row else -1

    async def get_for(self, fingerprint: str) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM feedback WHERE fingerprint = ? ORDER BY created_at DESC",
            (fingerprint,),
        )
        return [dict(row) for row in rows]

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    async def delete(self, feedback_id: int) -> None:
        await self.db.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))


class SuppressionStore:
    """Локальные suppression.

    Локальный suppression НЕ подавляет CI-находку (двойной контур gates):
    здесь — только фильтрация локального показа.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS suppressions (
                fingerprint TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'local',
                expires_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL
            );
            """
        )

    async def create(self, suppression: Suppression) -> None:
        await self.db.execute(
            """
            INSERT INTO suppressions (fingerprint, reason, scope, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                reason = excluded.reason,
                scope = excluded.scope,
                expires_at = excluded.expires_at
            """,
            (
                suppression.fingerprint,
                suppression.reason,
                suppression.scope,
                suppression.expires_at,
                suppression.created_at,
            ),
        )

    async def get(self, fingerprint: str) -> Suppression | None:
        row = await self.db.fetchone(
            "SELECT * FROM suppressions WHERE fingerprint = ?", (fingerprint,)
        )
        if row is None:
            return None
        return Suppression(
            fingerprint=row["fingerprint"],
            reason=row["reason"],
            scope=row["scope"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
        )

    async def list_all(self) -> list[Suppression]:
        rows = await self.db.fetchall("SELECT * FROM suppressions ORDER BY created_at DESC")
        return [
            Suppression(
                fingerprint=r["fingerprint"],
                reason=r["reason"],
                scope=r["scope"],
                expires_at=r["expires_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def delete(self, fingerprint: str) -> None:
        await self.db.execute("DELETE FROM suppressions WHERE fingerprint = ?", (fingerprint,))

    async def is_suppressed(self, fingerprint: str) -> bool:
        suppression = await self.get(fingerprint)
        if suppression is None:
            return False
        return not suppression.is_expired()

    async def filter_active(self, findings: list[Finding]) -> list[Finding]:
        """Убирает из списка находки с активным локальным suppression."""
        result = []
        for finding in findings:
            if not await self.is_suppressed(finding.fingerprint):
                result.append(finding)
        return result


class ScanCacheStore:
    """Кэш результатов сканирования (минимальная версия, возможно, уйдёт).

    Инвалидация по (file_hash, scanner, scanner_version, ruleset_hash).
    Пока храним только для Semgrep — остальные сканеры быстры и не кэшируются.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS scan_cache (
                file_hash TEXT NOT NULL,
                scanner TEXT NOT NULL,
                scanner_version TEXT NOT NULL,
                ruleset_hash TEXT NOT NULL,
                result_json TEXT NOT NULL,
                cached_at TIMESTAMP NOT NULL,
                PRIMARY KEY (file_hash, scanner, scanner_version, ruleset_hash)
            );
            """
        )

    async def get(
        self, file_hash: str, scanner: str, scanner_version: str, ruleset_hash: str
    ) -> str | None:
        row = await self.db.fetchone(
            """
            SELECT result_json FROM scan_cache
            WHERE file_hash = ? AND scanner = ? AND scanner_version = ? AND ruleset_hash = ?
            """,
            (file_hash, scanner, scanner_version, ruleset_hash),
        )
        return row["result_json"] if row else None

    async def put(
        self,
        file_hash: str,
        scanner: str,
        scanner_version: str,
        ruleset_hash: str,
        result_json: str,
    ) -> None:
        await self.db.execute(
            """
            INSERT OR REPLACE INTO scan_cache
                (file_hash, scanner, scanner_version, ruleset_hash, result_json, cached_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_hash, scanner, scanner_version, ruleset_hash, result_json, _now_iso()),
        )

    async def invalidate(self, scanner: str | None = None) -> None:
        if scanner:
            await self.db.execute("DELETE FROM scan_cache WHERE scanner = ?", (scanner,))
        else:
            await self.db.execute("DELETE FROM scan_cache")


class ProjectsStore:
    """Реестр известных проектов (arch §4.10).

    ``first_seen_at`` фиксируется один раз, ``last_seen_at`` обновляется при
    каждом старте сессии. ``project_path`` меняться не может — ``project_id``
    выводится из физического пути, а смена пути запрещена инвариантом №6.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id    TEXT PRIMARY KEY,
                project_alias TEXT NOT NULL,
                project_path  TEXT NOT NULL,
                first_seen_at TIMESTAMP NOT NULL,
                last_seen_at  TIMESTAMP NOT NULL
            );
            """
        )

    async def upsert(self, project_id: str, project_alias: str, project_path: str) -> None:
        now = _now_iso()
        await self.db.execute(
            """
            INSERT INTO projects (project_id, project_alias, project_path, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                project_alias = excluded.project_alias,
                project_path  = excluded.project_path,
                last_seen_at  = excluded.last_seen_at
            """,
            (project_id, project_alias, project_path, now, now),
        )

    async def get(self, project_id: str) -> dict[str, Any] | None:
        row = await self.db.fetchone("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        return dict(row) if row else None


class FindingIdentityStore:
    """Стабильная идентичность находки (arch §4.7).

    Живёт дольше ``fingerprint``: связывает ``logical_id`` с текущим
    fingerprint. ``first_seen_at`` фиксируется при первом появлении пары
    ``(project_id, logical_id)`` и не обновляется; ``last_fingerprint`` и
    ``last_seen_at`` обновляются при каждом повторном показе.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS finding_identity (
                logical_id       TEXT NOT NULL,
                project_id       TEXT NOT NULL,
                rule_id          TEXT NOT NULL,
                file_path        TEXT NOT NULL,
                first_seen_at    TIMESTAMP NOT NULL,
                last_fingerprint TEXT NOT NULL,
                last_seen_at     TIMESTAMP NOT NULL,
                PRIMARY KEY (project_id, logical_id)
            );
            """
        )

    async def upsert(
        self,
        project_id: str,
        logical_id: str,
        rule_id: str,
        file_path: str,
        fingerprint: str,
    ) -> None:
        now = _now_iso()
        await self.db.execute(
            """
            INSERT INTO finding_identity
                (logical_id, project_id, rule_id, file_path, first_seen_at, last_fingerprint, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, logical_id) DO UPDATE SET
                last_fingerprint = excluded.last_fingerprint,
                last_seen_at     = excluded.last_seen_at
            """,
            (logical_id, project_id, rule_id, file_path, now, fingerprint, now),
        )


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
        now = _now_iso()
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


class SqlAuditLogStore:
    """Журнал SQL-запросов ``query_findings_db`` (arch §4.7, требование F19).

    Хранит только текст запроса и метаданные. Запросы ограничены views и не
    могут содержать секретов (все значения в БД уже redacted), поэтому сам
    SQL логировать безопасно (инвариант №4 / §6 NF11).
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS sql_audit_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id    TEXT NOT NULL,
                session_id    TEXT NOT NULL,
                sql           TEXT NOT NULL,
                duration_ms   INTEGER,
                row_count     INTEGER,
                executed_at   TIMESTAMP NOT NULL
            );
            """
        )

    async def record(
        self,
        project_id: str,
        session_id: str,
        sql: str,
        duration_ms: int,
        row_count: int,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO sql_audit_log
                (project_id, session_id, sql, duration_ms, row_count, executed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, session_id, sql, duration_ms, row_count, _now_iso()),
        )
