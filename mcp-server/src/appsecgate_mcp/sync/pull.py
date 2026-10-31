"""Pull CI/global suppressions и центральной policy с master (MS-5)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from appsecgate_mcp.config.master_policy import validate_master_policy, write_master_policy
from appsecgate_mcp.models.finding import Suppression
from appsecgate_mcp.storage.db import Database
from appsecgate_mcp.storage.stores import RemoteSuppressionStore

_UTC = timedelta(0)


class PullError(ValueError):
    """Master недоступен или вернул ответ, нарушающий pull-контракт."""


@dataclass(frozen=True, slots=True)
class PullResult:
    suppression_count: int
    policy_present: bool


def _get_json(
    master_url: str, path: str, project_id: str, api_key: str, timeout: float
) -> dict[str, Any]:
    query = urllib.parse.urlencode({"project": project_id})
    request = urllib.request.Request(
        f"{master_url.rstrip('/')}{path}?{query}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise PullError(f"GET {path}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PullError(f"GET {path}: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PullError(f"GET {path}: invalid JSON") from exc
    if not isinstance(payload, dict):
        raise PullError(f"GET {path}: response must be a JSON object")
    return payload


def _validate_project(payload: dict[str, Any], project_id: str, path: str) -> None:
    if payload.get("project") != project_id:
        raise PullError(f"GET {path}: project mismatch")


def _validate_utc(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PullError(f"suppression {field} must be UTC ISO-8601 or null")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise PullError(f"suppression {field} must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != _UTC:
        raise PullError(f"suppression {field} must be UTC ISO-8601")
    return value


def _suppressions(payload: dict[str, Any], project_id: str) -> list[Suppression]:
    _validate_project(payload, project_id, "/v1/suppressions")
    rows = payload.get("suppressions")
    if not isinstance(rows, list):
        raise PullError("GET /v1/suppressions: suppressions must be a list")
    result: list[Suppression] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise PullError("suppression entry must be an object")
        fp = row.get("fp")
        scope = row.get("scope")
        reason = row.get("reason")
        if not isinstance(fp, str) or not fp or fp in seen:
            raise PullError("suppression fp must be non-empty and unique")
        if scope not in {"ci", "global"}:
            raise PullError("suppression scope must be ci or global")
        if reason is not None and not isinstance(reason, str):
            raise PullError("suppression reason must be a string or null")
        expires_at = _validate_utc(row.get("expires_at"), "expires_at")
        suppressed_at = _validate_utc(row.get("suppressed_at"), "suppressed_at")
        seen.add(fp)
        result.append(
            Suppression(
                fingerprint=fp,
                reason=reason or "",
                scope=scope,
                expires_at=expires_at,
                created_at=suppressed_at or datetime.now(UTC).isoformat(),
            )
        )
    return result


def _policy(payload: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    _validate_project(payload, project_id, "/v1/config")
    policy = payload.get("policy")
    try:
        if policy is not None:
            validate_master_policy(policy)
    except ValueError as exc:
        raise PullError(f"GET /v1/config: {exc}") from exc
    return policy


def pull_master(
    master_url: str,
    project_id: str,
    api_key: str,
    data_dir: str | Path,
    *,
    timeout: float = 30,
) -> PullResult:
    """Скачать и проверить оба ответа, затем применить их к локальному data-dir."""
    suppression_payload = _get_json(master_url, "/v1/suppressions", project_id, api_key, timeout)
    config_payload = _get_json(master_url, "/v1/config", project_id, api_key, timeout)
    suppressions = _suppressions(suppression_payload, project_id)
    policy = _policy(config_payload, project_id)

    db = Database(Path(data_dir) / "shown_findings.db")
    db.connect()
    try:
        store = RemoteSuppressionStore(db, project_id)
        store.init_schema()
        asyncio.run(store.replace_all(suppressions))
        write_master_policy(data_dir, project_id, policy)
    except (OSError, sqlite3.Error) as exc:
        raise PullError(f"cannot apply pulled state: {exc}") from exc
    finally:
        db.close()
    return PullResult(len(suppressions), policy is not None)
