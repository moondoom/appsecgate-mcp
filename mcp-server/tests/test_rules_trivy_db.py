"""Тесты статуса и seed Trivy DB (дизайн v1 §2.3, §5).

Проверяется чтение ``$TRIVY_CACHE_DIR/db/metadata.json``, вычисление возраста,
порог ``max_db_age_days`` → warning, отсутствие БД → warning, Java DB →
warning, а также идемпотентность seed-on-first-run. Все проверки fail-soft:
ни один сценарий не должен поднимать исключений.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from appsecgate_mcp.rules import trivy_db
from appsecgate_mcp.rules.trivy_db import (
    JAVA_DB_MISSING_WARNING,
    seed_trivy_db,
    trivy_db_status,
)


def _write_metadata(
    cache_dir: Path,
    *,
    updated_at: datetime,
    next_update: str | None = None,
) -> Path:
    """Пишет metadata.json Trivy DB и возвращает путь к нему."""
    db_dir = cache_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / "trivy.db").write_bytes(b"sqlite")
    payload: dict[str, object] = {"UpdatedAt": updated_at.isoformat()}
    if next_update is not None:
        payload["NextUpdate"] = next_update
    meta_path = db_dir / "metadata.json"
    meta_path.write_text(json.dumps(payload), encoding="utf-8")
    return meta_path


def test_status_missing_db_warns(tmp_path: Path):
    status = trivy_db_status(cache_dir=tmp_path / "trivy", max_age_days=30)
    assert status.present is False
    assert status.age_days is None
    assert status.warning is not None
    assert "not found" in status.warning
    # Отсутствие Java DB тоже отражено.
    assert status.java_warning == JAVA_DB_MISSING_WARNING


def test_status_fresh_db_no_warning(tmp_path: Path):
    cache = tmp_path / "trivy"
    now = datetime(2024, 10, 10, tzinfo=UTC)
    _write_metadata(cache, updated_at=now - timedelta(days=9))
    status = trivy_db_status(cache_dir=cache, max_age_days=30, now=now)

    assert status.present is True
    assert status.age_days == 9
    assert status.warning is None
    assert status.version == "2024-10-01"


def test_status_stale_db_warns(tmp_path: Path):
    cache = tmp_path / "trivy"
    now = datetime(2024, 10, 10, tzinfo=UTC)
    _write_metadata(cache, updated_at=now - timedelta(days=47))
    status = trivy_db_status(cache_dir=cache, max_age_days=30, now=now)

    assert status.present is True
    assert status.age_days == 47
    assert status.warning is not None
    assert "age: 47 days" in status.warning
    assert "threshold: 30" in status.warning


def test_status_nanosecond_timestamp_parsed(tmp_path: Path):
    cache = tmp_path / "trivy"
    now = datetime(2024, 10, 10, 12, tzinfo=UTC)
    db_dir = cache / "db"
    db_dir.mkdir(parents=True)
    # Trivy пишет наносекундную точность — datetime.fromisoformat её не ест.
    (db_dir / "metadata.json").write_text(
        json.dumps({"UpdatedAt": "2024-10-01T06:12:34.123456789Z"}),
        encoding="utf-8",
    )
    status = trivy_db_status(cache_dir=cache, max_age_days=30, now=now)
    assert status.present is True
    # Наносекунды распарсены: возраст посчитан (9 полных суток).
    assert status.age_days == 9


def test_status_broken_metadata_is_soft(tmp_path: Path):
    cache = tmp_path / "trivy"
    db_dir = cache / "db"
    db_dir.mkdir(parents=True)
    (db_dir / "metadata.json").write_text("{not json", encoding="utf-8")
    status = trivy_db_status(cache_dir=cache, max_age_days=30)
    # Файл есть, но распарсить нельзя — не падаем.
    assert status.present is True
    assert status.age_days is None


def test_java_db_warning_absent_when_java_db_present(tmp_path: Path):
    cache = tmp_path / "trivy"
    now = datetime(2024, 10, 10, tzinfo=UTC)
    _write_metadata(cache, updated_at=now - timedelta(days=1))
    java_dir = cache / "java-db"
    java_dir.mkdir(parents=True)
    (java_dir / "metadata.json").write_text("{}", encoding="utf-8")

    status = trivy_db_status(cache_dir=cache, max_age_days=30, now=now)
    assert status.java_db_present is True
    assert status.java_warning is None


def test_collect_warnings_aggregates(tmp_path: Path):
    status = trivy_db_status(cache_dir=tmp_path / "trivy", max_age_days=30)
    warnings = status.collect_warnings()
    assert len(warnings) == 2  # отсутствие DB + отсутствие Java DB


def test_seed_copies_when_absent(tmp_path: Path):
    seed = tmp_path / "seed"
    (seed / "db").mkdir(parents=True)
    (seed / "db" / "trivy.db").write_bytes(b"seed")
    cache = tmp_path / "cache"

    assert seed_trivy_db(seed_dir=seed, cache_dir=cache) is True
    assert (cache / "db" / "trivy.db").read_bytes() == b"seed"
    # Повторный вызов — идемпотентен, БД уже есть.
    assert seed_trivy_db(seed_dir=seed, cache_dir=cache) is False


def test_seed_noop_without_seed(tmp_path: Path):
    cache = tmp_path / "cache"
    assert seed_trivy_db(seed_dir=tmp_path / "nope", cache_dir=cache) is False
    assert not cache.exists()


def test_seed_dir_env_override(tmp_path: Path, monkeypatch):
    """`APPSECGATE_TRIVY_DB_SEED` переопределяет дефолтный seed-каталог."""
    seed = tmp_path / "seed"
    (seed / "db").mkdir(parents=True)
    (seed / "db" / "trivy.db").write_bytes(b"env-seed")
    cache = tmp_path / "cache"
    monkeypatch.setenv("APPSECGATE_TRIVY_DB_SEED", str(seed))

    # seed_dir не передан → берётся env-значение.
    assert seed_trivy_db(cache_dir=cache) is True
    assert (cache / "db" / "trivy.db").read_bytes() == b"env-seed"


def test_status_cache_dir_env_override(tmp_path: Path, monkeypatch):
    """`TRIVY_CACHE_DIR` определяет кэш для статуса (согласовано с entrypoint)."""
    cache = tmp_path / "trivy"
    now = datetime(2024, 10, 10, tzinfo=UTC)
    _write_metadata(cache, updated_at=now - timedelta(days=3))
    monkeypatch.setenv("TRIVY_CACHE_DIR", str(cache))

    status = trivy_db_status(max_age_days=30, now=now)
    assert status.present is True
    assert status.age_days == 3


async def test_sync_reports_failure_on_missing_binary(monkeypatch):
    """Отсутствие бинарника trivy → warning, без исключения."""
    from appsecgate_mcp.scanners import runner
    from appsecgate_mcp.scanners.runner import ScannerExecutionError

    async def fake_run(cmd, *, timeout=120, cwd=None):
        raise ScannerExecutionError(scanner="trivy", message="binary not found: trivy")

    # Ленивый импорт внутри sync_trivy_db → патчим раннер.
    monkeypatch.setattr(runner, "run_subprocess", fake_run)
    warning = await trivy_db.sync_trivy_db(timeout_seconds=1)
    assert warning is not None
    assert "sync failed" in warning
