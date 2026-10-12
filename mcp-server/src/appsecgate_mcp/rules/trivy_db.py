"""Статус и seed Trivy DB (дизайн v1 §2.3, §5).

Trivy хранит метаданные БД в ``$TRIVY_CACHE_DIR/db/metadata.json``:
``UpdatedAt`` — дата сборки БД, ``NextUpdate`` — рекомендованная дата
обновления. Возраст БД (``now - UpdatedAt``) сравнивается с порогом
``network.sync.max_db_age_days``; при превышении формируется warning по
шаблону из спеки. Java DB (сотни МБ) в образ не входит по умолчанию —
её отсутствие даёт warning ``trivy_java_db_missing``.

Модуль намеренно не импортирует ``config``/``scanners`` на верхнем уровне
(избегаем циклов): все параметры передаются примитивами, а запуск
внешнего процесса вынесен в ленивый импорт внутри ``sync_trivy_db``.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

# Дефолтные расположения (совпадают с Dockerfile/docker-compose).
DEFAULT_TRIVY_CACHE_DIR = "/home/appsecgate/.cache/trivy"
DEFAULT_TRIVY_DB_SEED = "/opt/appsecgate/trivy-db-seed"

# Маркер warning об отсутствии Java DB (см. дизайн v1 §2.3).
JAVA_DB_MISSING_WARNING = (
    "trivy_java_db_missing: Java DB not present; Java dependency scanning is limited "
    "(rebuild with WITH_JAVA_DB=true to include it)"
)


class TrivyDbStatus(BaseModel):
    """Статус локальной Trivy DB (для ``session_start`` и ``meta``)."""

    present: bool = False
    version: str = ""
    age_days: int | None = None
    path: str = ""
    next_update: str | None = None
    java_db_present: bool = False
    warning: str | None = None
    java_warning: str | None = None

    def collect_warnings(self) -> list[str]:
        """Список активных предупреждений (stale/отсутствие DB, Java DB)."""
        return [w for w in (self.warning, self.java_warning) if w]


def _default_cache_dir() -> Path:
    """Кэш Trivy: env ``TRIVY_CACHE_DIR`` или дефолт образа."""
    return Path(os.environ.get("TRIVY_CACHE_DIR", DEFAULT_TRIVY_CACHE_DIR))


def _default_seed_dir() -> Path:
    """Seed-каталог Trivy DB: env ``APPSECGATE_TRIVY_DB_SEED`` или дефолт образа.

    Согласовано с ``scripts/entrypoint.sh`` (тот же env-ключ).
    """
    return Path(os.environ.get("APPSECGATE_TRIVY_DB_SEED", DEFAULT_TRIVY_DB_SEED))


def _parse_iso(value: object) -> datetime | None:
    """Парсит ISO-8601 из metadata.json (устойчиво к ``Z`` и отсутствию tz).

    Trivy пишет наносекундные доли секунды (9 знаков), которые
    ``datetime.fromisoformat`` не принимает — обрезаем дробную часть
    до микросекунд перед повторной попыткой.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, _truncate_fraction(text)):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    return None


def _truncate_fraction(text: str) -> str:
    """Обрезает дробные доли секунды до 6 знаков (микросекунды)."""
    if "." not in text:
        return text
    head, _, tail = text.partition(".")
    offset_idx = len(tail)
    for i, ch in enumerate(tail):
        if ch in "+-Zz":
            offset_idx = i
            break
    fraction = tail[:offset_idx][:6]
    offset = tail[offset_idx:]
    return f"{head}.{fraction}{offset}"


def _load_json(path: Path) -> dict[str, object]:
    """Читает JSON-файл, возвращая пустой dict при любой ошибке (fail-soft)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _java_db_present(cache_dir: Path) -> bool:
    """True, если в кэше есть метаданные Java DB."""
    return (cache_dir / "java-db" / "metadata.json").exists()


def trivy_db_status(
    *,
    cache_dir: str | Path | None = None,
    max_age_days: int | None = 30,
    now: datetime | None = None,
) -> TrivyDbStatus:
    """Читает метаданные Trivy DB и формирует статус + warning (fail-soft).

    Никогда не поднимает исключений: отсутствие/битые метаданные — это
    статус ``present=False`` и warning, а не падение.
    """
    cache = Path(cache_dir) if cache_dir is not None else _default_cache_dir()
    meta_path = cache / "db" / "metadata.json"
    current = now or datetime.now(UTC)
    java_present = _java_db_present(cache)
    java_warning = None if java_present else JAVA_DB_MISSING_WARNING

    if not meta_path.exists():
        return TrivyDbStatus(
            present=False,
            path=str(meta_path),
            java_db_present=java_present,
            warning=(
                f"Trivy DB not found at {meta_path}: vulnerability scanning may be incomplete\n"
                "Action: rebuild container (seed DB) or set network.mode=online"
            ),
            java_warning=java_warning,
        )

    data = _load_json(meta_path)
    updated = _parse_iso(data.get("UpdatedAt")) or _parse_iso(data.get("DownloadedAt"))
    version = updated.date().isoformat() if updated else str(data.get("Version") or "")
    next_update_raw = data.get("NextUpdate")
    next_update = next_update_raw if isinstance(next_update_raw, str) else None

    age_days: int | None = None
    warning: str | None = None
    if updated is not None:
        age_days = max(0, (current - updated).days)
        if max_age_days is not None and age_days >= max_age_days:
            warning = (
                f"Trivy DB version: {version} (age: {age_days} days, "
                f"threshold: {max_age_days})\n"
                "Action: set network.mode=online or rebuild container"
            )

    return TrivyDbStatus(
        present=True,
        version=version,
        age_days=age_days,
        path=str(meta_path),
        next_update=next_update,
        java_db_present=java_present,
        warning=warning,
        java_warning=java_warning,
    )


async def sync_trivy_db(
    *,
    cache_dir: str | Path | None = None,
    timeout_seconds: int = 30,
) -> str | None:
    """Онлайн-синхронизация Trivy DB (один раз на ``session_start``).

    Возвращает warning-строку при неуспехе/таймауте, иначе ``None``.
    Fallback на локальную БД — ответственность вызывающей стороны:
    исключения наружу не пробрасываются.
    """
    # Ленивый импорт — избегаем цикла rules ↔ scanners на этапе импорта.
    from appsecgate_mcp.scanners.runner import ScannerExecutionError, run_subprocess

    cache = str(cache_dir) if cache_dir is not None else str(_default_cache_dir())
    cmd = ["trivy", "--download-db-only", "--cache-dir", cache]
    try:
        result = await run_subprocess(cmd, timeout=timeout_seconds)
    except ScannerExecutionError as exc:
        return f"trivy db sync failed: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or f"exit code {result.returncode}"
        return f"trivy db sync failed: {detail}"
    return None


def seed_trivy_db(
    *,
    seed_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> bool:
    """Seed-on-first-run: копирует БД из seed, если её ещё нет (дизайн v1 §5).

    Возвращает ``True``, если БД была засеяна, иначе ``False`` (уже есть
    или seed отсутствует). Идемпотентна и безопасна для вызова из entrypoint.
    """
    seed = Path(seed_dir) if seed_dir is not None else _default_seed_dir()
    cache = Path(cache_dir) if cache_dir is not None else _default_cache_dir()
    if (cache / "db" / "trivy.db").exists():
        return False
    if not (seed / "db").is_dir():
        return False
    cache.mkdir(parents=True, exist_ok=True)
    shutil.copytree(seed, cache, dirs_exist_ok=True)
    return True
