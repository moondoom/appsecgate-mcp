"""Миграции pre-1.0.0: schema_meta + drop-on-mismatch (ADR-0005 §2.7).

До 1.0.0 миграций нет: несовпадение ``schema_version`` означает полный drop
всех views и таблиц (включая ``sqlite_sequence``) с последующим пересозданием
схемы store-классами. При 1.0.0 поверх этого механизма появятся настоящие
миграции.

Точка вызова — ``init_databases()`` (``storage/db.py``): тесты, создающие
store вручную, минуют этот модуль, а свежая БД получает версию без дропа.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from appsecgate_mcp.storage.db import Database

SCHEMA_VERSION = "1"

_SCHEMA_META_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL          -- 'schema_version' -> '1'
);
"""

logger = logging.getLogger(__name__)


def _quote(name: str) -> str:
    """Экранирует идентификатор из sqlite_master для DROP-выражений."""
    return '"' + name.replace('"', '""') + '"'


def _object_names(db: Database, obj_type: str) -> list[str]:
    rows = db._fetchall("SELECT name FROM sqlite_master WHERE type = ?", (obj_type,))
    return [str(r["name"]) for r in rows]


def _read_schema_version(db: Database) -> str | None:
    row = db._fetchone("SELECT value FROM schema_meta WHERE key = 'schema_version'")
    return str(row["value"]) if row else None


def _write_schema_version(db: Database) -> None:
    db._write(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
        (SCHEMA_VERSION,),
    )


def drop_all(db: Database) -> None:
    """Удаляет все views и таблицы (включая ``sqlite_sequence``) в одной транзакции.

    Порядок важен: сначала views (DROP TABLE падает, если на таблицу ссылается
    view), затем таблицы. ``sqlite_sequence`` попадает в выборку из
    ``sqlite_master`` как обычная таблица и удаляется вместе со всеми.
    """
    with db._lock:
        conn = db._conn
        assert conn is not None
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")
        try:
            for name in _object_names(db, "view"):
                conn.execute(f"DROP VIEW IF EXISTS {_quote(name)}")
            for name in _object_names(db, "table"):
                if name == "sqlite_sequence":
                    # SQLite запрещает DROP TABLE sqlite_sequence (и не чистит её
                    # записи при дропе AUTOINCREMENT-таблиц) — обнуляем счётчики.
                    conn.execute("DELETE FROM sqlite_sequence")
                else:
                    conn.execute(f"DROP TABLE IF EXISTS {_quote(name)}")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


def ensure_schema_version(db: Database) -> bool:
    """Проверяет ``schema_version``; при несовпадении дропает всё.

    - Пустая (свежая) БД — только проставляется версия, без дропа.
    - БД без ``schema_meta`` (легаси) или с другой версией — ``drop_all``
      + warning в лог; схему пересоздадут store-классы после возврата.
    - Версия совпадает — ничего не делает.

    Возвращает ``True``, если потребовался drop.
    """
    objects_exist = bool(_object_names(db, "table") or _object_names(db, "view"))
    db._execute_ddl(_SCHEMA_META_DDL)
    version = _read_schema_version(db)
    if version == SCHEMA_VERSION:
        return False
    if version is None and not objects_exist:
        _write_schema_version(db)
        return False

    logger.warning(
        "schema_version mismatch on %s: expected '%s', found %s — dropping",
        db.path,
        SCHEMA_VERSION,
        version,
    )
    drop_all(db)
    db._execute_ddl(_SCHEMA_META_DDL)
    _write_schema_version(db)
    return True
