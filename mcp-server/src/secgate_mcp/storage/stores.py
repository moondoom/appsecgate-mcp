"""Все хранилища предметной области в одном модуле.

На Фазе 1 держим store-классы вместе: проще навигировать и править.
Отдельные файлы появятся при росте (Фаза 2), если понадобятся.

Хранилища:
  * ShownFindingsStore — журнал показанных находок (shown_findings.db)
  * FeedbackStore      — обратная связь разработчика (feedback.db)
  * SuppressionStore   — локальные suppression
  * ScanCacheStore     — кэш результатов сканирования (минимальный, возможно уйдёт)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from secgate_mcp.models.finding import Finding, Suppression
from secgate_mcp.storage.db import Database


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ShownFindingsStore:
    """Журнал находок, показанных разработчику (arch §3.5)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def init_schema(self) -> None:
        self.db._execute_ddl(
            """
            CREATE TABLE IF NOT EXISTS shown_findings (
                fingerprint TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                severity TEXT NOT NULL,
                scanner TEXT NOT NULL,
                first_shown_at TIMESTAMP NOT NULL,
                last_shown_at TIMESTAMP NOT NULL,
                show_count INTEGER DEFAULT 1,
                status TEXT NOT NULL,
                fixed_at TIMESTAMP,
                suppressed_at TIMESTAMP,
                suppress_reason TEXT
            );
            """
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_shown_file ON shown_findings(file_path)"
        )
        self.db._execute_ddl(
            "CREATE INDEX IF NOT EXISTS idx_shown_status ON shown_findings(status)"
        )

    async def record_shown(self, finding: Finding) -> None:
        now = _now_iso()
        await self.db.execute(
            """
            INSERT INTO shown_findings (fingerprint, rule_id, file_path, severity, scanner,
                                        first_shown_at, last_shown_at, show_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'SHOWN')
            ON CONFLICT(fingerprint) DO UPDATE SET
                last_shown_at = excluded.last_shown_at,
                show_count = show_count + 1
            """,
            (
                finding.fingerprint,
                finding.rule_id,
                finding.file_path,
                finding.severity.value,
                finding.scanner,
                now,
                now,
            ),
        )

    async def record_shown_batch(self, findings: list[Finding]) -> None:
        now = _now_iso()
        rows = [
            (f.fingerprint, f.rule_id, f.file_path, f.severity.value, f.scanner, now, now)
            for f in findings
        ]
        if not rows:
            return
        await self.db.execute_many(
            """
            INSERT INTO shown_findings (fingerprint, rule_id, file_path, severity, scanner,
                                        first_shown_at, last_shown_at, show_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'SHOWN')
            ON CONFLICT(fingerprint) DO UPDATE SET
                last_shown_at = excluded.last_shown_at,
                show_count = show_count + 1
            """,
            rows,
        )

    async def mark_fixed(self, fingerprint: str) -> None:
        await self.db.execute(
            "UPDATE shown_findings SET status = 'FIXED', fixed_at = ? WHERE fingerprint = ?",
            (_now_iso(), fingerprint),
        )

    async def mark_suppressed(self, fingerprint: str, reason: str) -> None:
        await self.db.execute(
            """
            UPDATE shown_findings
            SET status = 'SUPPRESSED', suppressed_at = ?, suppress_reason = ?
            WHERE fingerprint = ?
            """,
            (_now_iso(), reason, fingerprint),
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

    async def get(self, file_hash: str, scanner: str, scanner_version: str, ruleset_hash: str) -> str | None:
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
