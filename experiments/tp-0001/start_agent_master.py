#!/usr/bin/env python3
"""Поднимает master для agent300 поверх PostgreSQL.

PostgreSQL — постоянный контейнер с named volume: БД сохраняется на всём
протяжении эксперимента и переживает перезапуски master. Master stateless
(--rm), вся durable-нагрузка в PostgreSQL. Пароль генерируется один раз и
хранится в runtime/agent300-postgres.env (gitignored).
"""

from __future__ import annotations

import json
import secrets
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NETWORK = "appsecgate-mcp_appsecgate"
PG_NAME = "appsecgate-postgres"
PG_VOLUME = "appsecgate-postgres-data"
MASTER_NAME = "appsecgate-agent300-master"
ENV_FILE = ROOT / "runtime" / "agent300-postgres.env"


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def _load_password() -> str:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("APPSECGATE_POSTGRES_PASSWORD="):
                return line.split("=", 1)[1]
    password = secrets.token_urlsafe(24)
    ENV_FILE.write_text(f"APPSECGATE_POSTGRES_PASSWORD={password}\n")
    ENV_FILE.chmod(0o600)
    return password


def main() -> None:
    keys = json.loads((ROOT / "runtime" / "agent300-keys.json").read_text())
    password = _load_password()
    if _run("docker", "network", "inspect", NETWORK, check=False).returncode != 0:
        _run("docker", "network", "create", NETWORK)

    if _run("docker", "inspect", PG_NAME, check=False).returncode != 0:
        _run(
            "docker",
            "run",
            "-d",
            "--name",
            PG_NAME,
            "--restart",
            "unless-stopped",
            "--network",
            NETWORK,
            "-p",
            "127.0.0.1:5432:5432",
            "-e",
            "POSTGRES_DB=appsecgate",
            "-e",
            "POSTGRES_USER=appsecgate",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "-v",
            f"{PG_VOLUME}:/var/lib/postgresql/data",
            "postgres:16",
        )
    elif _run("docker", "inspect", "-f", "{{.State.Running}}", PG_NAME).stdout.strip() != "true":
        _run("docker", "start", PG_NAME)

    for _ in range(60):
        ready = _run(
            "docker", "exec", PG_NAME, "pg_isready", "-U", "appsecgate", "-d", "appsecgate",
            check=False,
        )
        if ready.returncode == 0:
            break
        time.sleep(2)
    else:
        raise SystemExit("postgres did not become ready in 120s")

    _run("docker", "rm", "-f", MASTER_NAME, check=False)
    result = _run(
        "docker",
        "run",
        "-d",
        "--name",
        MASTER_NAME,
        "--restart",
        "unless-stopped",
        "--network",
        NETWORK,
        "-p",
        "127.0.0.1:8001:8000",
        "-e",
        f"APPSECGATE_MASTER_API_KEYS={json.dumps(keys)}",
        "-e",
        f"APPSECGATE_MASTER_DATABASE_URL=postgresql://appsecgate:{password}@{PG_NAME}:5432/appsecgate",
        "moondoom/appsecgate-master:0.1.0",
    )
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
