"""Общие фикстуры тестов: master-БД и store-классы."""

from __future__ import annotations

import pytest

from appsecgate_master.storage import AggregateStore, MasterEventStore, init_schema
from appsecgate_master.storage.db import Database


@pytest.fixture()
async def master_db(tmp_path):
    """SQLite-БД master в temp-каталоге со схемой v1."""
    db = Database(tmp_path / "master.db")
    db.connect()
    await init_schema(db)
    yield db
    db.close()


@pytest.fixture()
def events_store(master_db: Database) -> MasterEventStore:
    return MasterEventStore(master_db)


@pytest.fixture()
def aggregates_store(master_db: Database) -> AggregateStore:
    return AggregateStore(master_db)
