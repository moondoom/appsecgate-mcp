"""Настройки master HTTP API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path.home() / ".appsecgate" / "master" / "master.db"


def _validate_api_keys(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ValueError("APPSECGATE_MASTER_API_KEYS must be a non-empty JSON object")
    if any(not isinstance(project, str) or not project for project in value):
        raise ValueError("master API key project names must be non-empty strings")
    if any(not isinstance(key, str) or not key for key in value.values()):
        raise ValueError("master API keys must be non-empty strings")
    if len(set(value.values())) != len(value):
        raise ValueError("master API keys must be unique per project")
    return dict(value)


@dataclass(slots=True)
class MasterSettings:
    """Настройки процесса master; секреты не включаются в логи приложения."""

    db_path: Path
    api_keys: dict[str, str]
    database_url: str | None = None

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path).expanduser()
        self.api_keys = _validate_api_keys(self.api_keys)
        if self.database_url is not None and not self.database_url.startswith("postgresql://"):
            raise ValueError("APPSECGATE_MASTER_DATABASE_URL must use postgresql://")

    @classmethod
    def from_env(cls) -> MasterSettings:
        raw_keys = os.environ.get("APPSECGATE_MASTER_API_KEYS", "")
        try:
            parsed = json.loads(raw_keys)
        except json.JSONDecodeError as exc:
            raise ValueError("APPSECGATE_MASTER_API_KEYS must contain valid JSON") from exc
        return cls(
            db_path=Path(os.environ.get("APPSECGATE_MASTER_DB", str(DEFAULT_DB_PATH))),
            api_keys=_validate_api_keys(parsed),
            database_url=os.environ.get("APPSECGATE_MASTER_DATABASE_URL") or None,
        )
