"""Per-project центральная политика, скачанная edge sync (MS-5)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from appsecgate_mcp.config.models import Config

ALLOWED_POLICY_KEYS = frozenset({"gates", "rules"})


def master_policy_path(data_dir: str | Path, project_id: str) -> Path:
    if not project_id or Path(project_id).name != project_id or project_id in {".", ".."}:
        raise ValueError("project_id is not safe for master policy storage")
    return Path(data_dir) / "master-policies" / f"{project_id}.json"


def validate_master_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise ValueError("master policy must be a JSON object")
    unknown = set(policy) - ALLOWED_POLICY_KEYS
    if unknown:
        raise ValueError(f"master policy contains forbidden sections: {sorted(unknown)}")
    Config.model_validate(policy)
    return policy


def load_master_policy(data_dir: str | Path, project_id: str) -> dict[str, Any]:
    path = master_policy_path(data_dir, project_id)
    if not path.is_file():
        return {}
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read master policy: {path}") from exc
    return validate_master_policy(policy)


def write_master_policy(
    data_dir: str | Path, project_id: str, policy: dict[str, Any] | None
) -> None:
    path = master_policy_path(data_dir, project_id)
    if policy is None:
        path.unlink(missing_ok=True)
        return
    validate_master_policy(policy)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(policy, fh, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
