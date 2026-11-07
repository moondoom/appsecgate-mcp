from __future__ import annotations

import json
from typing import Any

from appsecgate_master.storage.db import Database

_CVE_DDL = """
CREATE TABLE IF NOT EXISTS cve_records (
    cve_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cve_affected_ranges (
    cve_id TEXT NOT NULL,
    ecosystem TEXT NOT NULL,
    package TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (cve_id, ecosystem, package)
);
"""

_SQLITE_VIEWS = """
CREATE VIEW IF NOT EXISTS v_triage_verdicts AS
SELECT
    project_key, fp, client_event_id,
    json_extract(payload, '$.verdict_id') AS verdict_id,
    json_extract(payload, '$.supersedes_verdict_id') AS supersedes_verdict_id,
    json_extract(payload, '$.run_id') AS run_id,
    json_extract(payload, '$.verdict') AS verdict,
    json_extract(payload, '$.verdict_source') AS verdict_source,
    json_extract(payload, '$.review_status') AS review_status,
    json_extract(payload, '$.rule_id') AS rule_id,
    json_extract(payload, '$.package') AS package,
    json_extract(payload, '$.ecosystem') AS ecosystem,
    json_extract(payload, '$.cve_id') AS cve_id,
    json_extract(payload, '$.explanation') AS explanation,
    json_extract(payload, '$.evidence') AS evidence,
    json_extract(payload, '$.agent_version') AS agent_version,
    json_extract(payload, '$.model') AS model,
    json_extract(payload, '$.prompt_sha256') AS prompt_sha256,
    json_extract(payload, '$.created_at') AS created_at,
    at,
    json_extract(payload, '$.confidence') AS confidence,
    json_extract(payload, '$.actor_id') AS actor_id,
    json_extract(payload, '$.revision_reason') AS revision_reason,
    json_extract(payload, '$.scanner') AS scanner,
    json_extract(payload, '$.ruleset_hash') AS ruleset_hash,
    json_extract(payload, '$.rule_hash') AS rule_hash,
    json_extract(payload, '$.rule_hash_status') AS rule_hash_status,
    json_extract(payload, '$.confidence_level') AS confidence_level,
    json_extract(payload, '$.model_confidence_level') AS model_confidence_level,
    json_extract(payload, '$.model_verdict') AS model_verdict,
    json_extract(payload, '$.downgrade_reason') AS downgrade_reason,
    json_extract(payload, '$.failure_reason') AS failure_reason,
    json_extract(payload, '$.failure_detail') AS failure_detail,
    json_extract(payload, '$.evidence_basis') AS evidence_basis,
    json_extract(payload, '$.evidence_quote') AS evidence_quote,
    json_extract(payload, '$.source_file') AS source_file,
    json_extract(payload, '$.start_line') AS start_line,
    json_extract(payload, '$.end_line') AS end_line,
    json_extract(payload, '$.read_event_id') AS read_event_id,
    json_extract(payload, '$.quote_hash') AS quote_hash,
    json_extract(payload, '$.reasoning') AS reasoning,
    json_extract(payload, '$.prompt_mode') AS prompt_mode
FROM events WHERE event_type = 'triage_verdicted';
CREATE VIEW IF NOT EXISTS v_triage_knowledge AS
SELECT
    verdict_id, supersedes_verdict_id, verdict, rule_id, package, ecosystem,
    cve_id, explanation, evidence, agent_version, model, created_at, at,
    confidence_level, evidence_basis
FROM v_triage_verdicts
WHERE verdict_source = 'human' AND review_status = 'confirmed';
CREATE VIEW IF NOT EXISTS v_cve AS
SELECT cve_id, payload, source, fetched_at, content_hash FROM cve_records;
CREATE VIEW IF NOT EXISTS v_cve_affected AS
SELECT cve_id, ecosystem, package, payload FROM cve_affected_ranges;
"""

_POSTGRES_VIEWS = _SQLITE_VIEWS.replace(
    "json_extract(payload, '$.", "payload::jsonb ->> '"
).replace("') AS", "' AS")


class KnowledgeStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def init_schema(self) -> None:
        await self.db.execute_script(_CVE_DDL)
        views = _POSTGRES_VIEWS if getattr(self.db, "is_postgres", False) else _SQLITE_VIEWS
        if getattr(self.db, "is_postgres", False):
            views = views.replace("CREATE VIEW IF NOT EXISTS", "CREATE OR REPLACE VIEW")
            views = views.replace(
                "CREATE OR REPLACE VIEW v_triage_verdicts AS",
                "CREATE OR REPLACE VIEW v_triage_verdicts WITH (security_invoker = true) AS",
            )
        await self.db.execute_script(views)

    async def upsert_cve(
        self,
        record: dict[str, Any],
        affected: list[dict[str, Any]],
        *,
        source: str,
        fetched_at: str,
        content_hash: str,
    ) -> None:
        cve_id = str(record["cve_id"])
        await self.db.execute(
            "INSERT OR REPLACE INTO cve_records "
            "(cve_id, payload, source, fetched_at, content_hash) VALUES (?, ?, ?, ?, ?)",
            (cve_id, json.dumps(record, ensure_ascii=False), source, fetched_at, content_hash),
        )
        for item in affected:
            await self.db.execute(
                "INSERT OR REPLACE INTO cve_affected_ranges "
                "(cve_id, ecosystem, package, payload) VALUES (?, ?, ?, ?)",
                (
                    cve_id,
                    item["ecosystem"],
                    item["package"],
                    json.dumps(item, ensure_ascii=False),
                ),
            )
