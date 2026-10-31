"""Помощники тестов edge-синхронизации (MS-3, appsecgate_mcp.sync)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Схема shown_findings.db, достаточная для экспорта (зеркало
# storage/stores/*; полные ограничения не нужны тестам).
_SHOWN_DDL = """
CREATE TABLE shown_findings (
    fingerprint          TEXT PRIMARY KEY,
    project_id           TEXT NOT NULL,
    rule_id              TEXT NOT NULL,
    file_path            TEXT NOT NULL,
    severity             TEXT NOT NULL,
    scanner              TEXT NOT NULL,
    category             TEXT NOT NULL,
    status               TEXT NOT NULL,
    status_updated_at    TIMESTAMP NOT NULL,
    missed_scan_count    INTEGER NOT NULL DEFAULT 0,
    first_seen_branch    TEXT,
    first_seen_commit    TEXT,
    last_seen_branch     TEXT,
    last_seen_commit     TEXT,
    first_shown_at       TIMESTAMP,
    last_shown_at        TIMESTAMP,
    show_count           INTEGER NOT NULL DEFAULT 0,
    first_seen_at        TIMESTAMP NOT NULL,
    last_seen_at         TIMESTAMP NOT NULL,
    scan_count           INTEGER NOT NULL DEFAULT 1,
    fixed_at             TIMESTAMP,
    fixed_confirmed_by   TEXT,
    suppressed_at        TIMESTAMP,
    suppress_reason      TEXT,
    wont_fix_at          TIMESTAMP,
    wont_fix_reason      TEXT
);
"""

_SUPPRESSIONS_DDL = """
CREATE TABLE suppressions (
    project_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    reason TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'local',
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (project_id, fingerprint)
);
"""

_DEFAULT_TIMES = "2026-10-01T10:00:00.000000+00:00"

_SHOWN_DEFAULTS = {
    "project_id": "pid-1",
    "rule_id": "rule.one",
    "file_path": "src/a.py",
    "severity": "high",
    "scanner": "semgrep",
    "category": "sast",
    "status": "SHOWN",
    "status_updated_at": _DEFAULT_TIMES,
    "first_seen_at": _DEFAULT_TIMES,
    "last_seen_at": _DEFAULT_TIMES,
}

_SUPPRESSION_DEFAULTS = {
    "project_id": "pid-1",
    "reason": "",
    "scope": "local",
    "expires_at": None,
    "created_at": _DEFAULT_TIMES,
}


def make_db(tmp_path: Path) -> Path:
    """Создаёт пустую shown_findings.db с таблицами shown_findings + suppressions."""
    path = tmp_path / "shown_findings.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SHOWN_DDL + "\n" + _SUPPRESSIONS_DDL)
    conn.commit()
    conn.close()
    return path


def insert_shown(db: Path, fp: str, **fields) -> None:
    """Вставляет строку shown_findings; неуказанные поля — безопасные дефолты."""
    row = {**_SHOWN_DEFAULTS, "fingerprint": fp, **fields}
    _insert(db, "shown_findings", row)


def insert_suppression(db: Path, fp: str, **fields) -> None:
    """Вставляет строку suppressions; неуказанные поля — безопасные дефолты."""
    row = {**_SUPPRESSION_DEFAULTS, "fingerprint": fp, **fields}
    _insert(db, "suppressions", row)


def _insert(db: Path, table: str, row: dict) -> None:
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn = sqlite3.connect(db)
    conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        tuple(row.values()),
    )
    conn.commit()
    conn.close()
