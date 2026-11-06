from __future__ import annotations

import pytest
from helpers import make_event, uid

from appsecgate_master.storage.query import run_query
from appsecgate_master.storage.stores.knowledge import KnowledgeStore


def _triage(*, project="proj", source="model", status="unreviewed", at="2026-11-01T00:00:00Z"):
    verdict_id = uid()
    return make_event(
        "triage_verdicted",
        project_key=project,
        at=at,
        verdict_id=verdict_id,
        client_event_id=verdict_id,
        run_id="run-1",
        verdict="FALSE_POSITIVE",
        confidence=85,
        verdict_source=source,
        actor_id=f"{source}:test",
        revision_reason="ttl_expired",
        review_status=status,
        scanner="semgrep",
        rule_id="rule-1",
        ruleset_hash="sha256:rules",
        rule_hash="sha256:rule",
        rule_hash_status="definition_sha256",
        package="pkg",
        ecosystem="npm",
        cve_id="CVE-2026-0001",
        explanation="example only",
        evidence=[{"kind": "scanner", "id": "ev-1"}],
        created_at=at,
    )


async def test_triage_views_enforce_project_knowledge_and_cutoff(master_db, events_store):
    await events_store.ingest([_triage(), _triage(project="other")])
    await events_store.ingest(
        [
            _triage(
                source="human",
                status="confirmed",
                at="2026-11-02T00:00:00Z",
            )
        ]
    )

    project_rows = await run_query(
        master_db,
        "SELECT fp, verdict, confidence, actor_id, revision_reason, ruleset_hash, rule_hash "
        "FROM v_triage_verdicts",
        None,
        "proj",
        None,
    )
    knowledge = await run_query(
        master_db,
        "SELECT verdict, created_at FROM v_triage_knowledge",
        None,
        "proj",
        "2026-11-01T12:00:00Z",
    )

    assert project_rows["row_count"] == 2
    assert project_rows["rows"][0]["confidence"] == 85
    assert project_rows["rows"][0]["actor_id"] == "model:test"
    assert project_rows["rows"][0]["revision_reason"] == "ttl_expired"
    assert project_rows["rows"][0]["ruleset_hash"] == "sha256:rules"
    assert project_rows["rows"][0]["rule_hash"] == "sha256:rule"
    assert knowledge["row_count"] == 0
    later = await run_query(master_db, "SELECT verdict FROM v_triage_knowledge", None, "proj", None)
    assert later["row_count"] == 1
    assert "project_key" not in later["rows"][0]
    assert "verdict_source" not in later["rows"][0]


async def test_cve_ingest_and_read_only_query(master_db):
    await KnowledgeStore(master_db).upsert_cve(
        {
            "cve_id": "CVE-2026-0001",
            "description": "test vulnerability",
            "cvss": {"score": 9.8},
        },
        [{"ecosystem": "npm", "package": "pkg", "fixed": "1.2.3"}],
        source="osv",
        fetched_at="2026-11-03T00:00:00Z",
        content_hash="hash-1",
    )

    cve = await run_query(
        master_db,
        "SELECT cve_id, payload FROM v_cve WHERE cve_id = ?",
        ["CVE-2026-0001"],
        "proj",
        None,
    )
    affected = await run_query(
        master_db,
        "SELECT package, payload FROM v_cve_affected WHERE cve_id = ?",
        ["CVE-2026-0001"],
        "proj",
        None,
    )

    assert cve["row_count"] == 1
    assert affected["rows"][0]["package"] == "pkg"
    with pytest.raises(ValueError):
        await run_query(master_db, "DELETE FROM v_cve", None, "proj", None)
