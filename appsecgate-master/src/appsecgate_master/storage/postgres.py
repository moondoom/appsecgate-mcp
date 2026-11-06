from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

import psycopg
from psycopg.rows import dict_row

_PROJECT: ContextVar[str] = ContextVar("appsecgate_master_project", default="")
_TX_CONNECTION: ContextVar[Any] = ContextVar("appsecgate_master_pg_connection", default=None)


def set_project(project_key: str) -> None:
    _PROJECT.set(project_key)


def _sql(statement: str) -> str:
    statement = statement.replace("?", "%s").replace("%s IS NULL", "%s::text IS NULL")
    if re.search(r"INSERT INTO events \(", statement):
        return statement + " ON CONFLICT (client_event_id) DO NOTHING"
    match = re.search(r"INSERT OR REPLACE INTO (\w+) \(([^)]+)\)(.*)", statement, re.DOTALL)
    if match:
        table, raw_columns, suffix = match.groups()
        columns = [item.strip() for item in raw_columns.split(",")]
        conflicts = {
            "schema_meta": "key",
            "cve_records": "cve_id",
            "cve_affected_ranges": "cve_id, ecosystem, package",
        }
        conflict = conflicts.get(table, "project_key, fp")
        assignments = ", ".join(f"{column}=EXCLUDED.{column}" for column in columns)
        return (
            f"INSERT INTO {table} ({raw_columns}){suffix} "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {assignments}"
        )
    return statement


def _ddl(statement: str) -> str:
    statement = re.sub(r"CREATE TRIGGER.*?END;", "", statement, flags=re.DOTALL)
    return statement.replace(
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY",
    )


class PostgresDatabase:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.is_postgres = True

    def _connect(self) -> Any:
        connection = psycopg.connect(self.dsn, row_factory=dict_row)
        connection.execute("SELECT set_config('app.project_key', %s, false)", (_PROJECT.get(),))
        return connection

    def close(self) -> None:
        return

    def _write(self, statement: str, params: Sequence[Any]) -> int:
        query = _sql(statement)
        transaction = _TX_CONNECTION.get()
        if transaction is not None:
            cursor = transaction.execute(query, params)
            return cursor.rowcount
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            return cursor.rowcount

    def _fetchone(self, statement: str, params: Sequence[Any]) -> dict[str, Any] | None:
        connection = _TX_CONNECTION.get()
        if connection is not None:
            return connection.execute(_sql(statement), params).fetchone()
        with self._connect() as connection:
            return connection.execute(_sql(statement), params).fetchone()

    def _fetchall(self, statement: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        connection = _TX_CONNECTION.get()
        if connection is not None:
            return list(connection.execute(_sql(statement), params).fetchall())
        with self._connect() as connection:
            return list(connection.execute(_sql(statement), params).fetchall())

    def _execute_script(self, statement: str) -> None:
        with self._connect() as connection:
            connection.execute(_ddl(statement))

    async def execute(self, statement: str, params: Sequence[Any] = ()) -> None:
        await asyncio.to_thread(self._write, statement, params)

    async def execute_rowcount(self, statement: str, params: Sequence[Any] = ()) -> int:
        return await asyncio.to_thread(self._write, statement, params)

    async def execute_many(self, statement: str, params_list: Sequence[Sequence[Any]]) -> None:
        query = _sql(statement)

        def run() -> None:
            connection = _TX_CONNECTION.get()
            if connection is not None:
                connection.cursor().executemany(query, params_list)
                return
            with self._connect() as owned:
                owned.cursor().executemany(query, params_list)

        await asyncio.to_thread(run)

    async def execute_script(self, statement: str) -> None:
        await asyncio.to_thread(self._execute_script, statement)

    async def fetchone(self, statement: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._fetchone, statement, params)

    async def fetchall(self, statement: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetchall, statement, params)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        if _TX_CONNECTION.get() is not None:
            yield
            return
        connection = await asyncio.to_thread(self._connect)
        token = _TX_CONNECTION.set(connection)
        try:
            yield
        except BaseException:
            await asyncio.to_thread(connection.rollback)
            raise
        else:
            await asyncio.to_thread(connection.commit)
        finally:
            _TX_CONNECTION.reset(token)
            await asyncio.to_thread(connection.close)

    async def authenticate_key(self, api_key: str) -> str | None:
        digest = hashlib.sha256(api_key.encode()).hexdigest()
        row = await self.fetchone("SELECT project_key FROM api_keys WHERE key_hash = %s", (digest,))
        return str(row["project_key"]) if row else None

    async def init_security(self, api_keys: dict[str, str]) -> None:
        await self.execute_script(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS api_keys (
                key_hash TEXT PRIMARY KEY,
                project_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS roles (name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS project_memberships (
                user_id BIGINT, project_key TEXT, role_name TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
            );
            """
        )
        for project, api_key in api_keys.items():
            digest = hashlib.sha256(api_key.encode()).hexdigest()
            await self.execute(
                "INSERT INTO api_keys (key_hash, project_key, created_at) VALUES (%s, %s, %s) "
                "ON CONFLICT (key_hash) DO NOTHING",
                (digest, project, "1970-01-01T00:00:00Z"),
            )
        await self.execute_script(
            """
            CREATE OR REPLACE FUNCTION reject_mutation() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'append-only table'; END;
            $$ LANGUAGE plpgsql;
            """
        )
        for table in ("events", "audit_log"):
            await self.execute_script(
                f"""
                DROP TRIGGER IF EXISTS {table}_append_update ON {table};
                CREATE TRIGGER {table}_append_update BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION reject_mutation();
                DROP TRIGGER IF EXISTS {table}_append_delete ON {table};
                CREATE TRIGGER {table}_append_delete BEFORE DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION reject_mutation();
                """
            )
        for table in ("events", "audit_log", "aggregates"):
            await self.execute_script(
                f"""
                ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
                DROP POLICY IF EXISTS project_isolation ON {table};
                CREATE POLICY project_isolation ON {table}
                USING (project_key = current_setting('app.project_key', true))
                WITH CHECK (project_key = current_setting('app.project_key', true));
                """
            )


async def init_postgres(dsn: str) -> PostgresDatabase:
    return PostgresDatabase(dsn)
