"""Общие фикстуры тестов: master-БД, store-классы и HTTP-клиент."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from appsecgate_master.api import MasterSettings, create_app
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


@pytest.fixture()
def master_settings(tmp_path) -> MasterSettings:
    return MasterSettings(
        db_path=tmp_path / "api-master.db",
        api_keys={"proj": "proj-key", "other": "other-key"},
    )


@pytest.fixture()
def master_client(master_settings: MasterSettings):
    with TestClient(create_app(master_settings)) as client:
        yield client
