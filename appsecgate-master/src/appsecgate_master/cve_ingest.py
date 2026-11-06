from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from appsecgate_master.api.config import MasterSettings
from appsecgate_master.storage.db import init_database
from appsecgate_master.storage.stores.knowledge import KnowledgeStore


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a frozen OSV/NVD snapshot into master")
    parser.add_argument(
        "path", type=Path, help="JSON snapshot with records, affected and provenance"
    )
    return parser.parse_args()


async def main() -> None:
    args = _args()
    payload = json.loads(args.path.read_text())
    settings = MasterSettings.from_env()
    db = await init_database(settings.db_path, settings.database_url)
    store = KnowledgeStore(db)
    await store.init_schema()
    try:
        for record in payload["records"]:
            await store.upsert_cve(
                record,
                payload.get("affected", {}).get(record["cve_id"], []),
                source=payload["source"],
                fetched_at=payload["fetched_at"],
                content_hash=payload["content_hash"],
            )
    finally:
        db.close()
    print(json.dumps({"imported": len(payload["records"])}))


if __name__ == "__main__":
    asyncio.run(main())
