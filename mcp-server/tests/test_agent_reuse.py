from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.models import AgentConfig
from appsecgate_mcp.agent.reuse import reuse_prior_verdicts

_NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
_RULESET = "sha256:rules"


def _config(tmp_path, **overrides):
    values = {
        "project": tmp_path,
        "data_dir": tmp_path / "data",
        "llm_url": "http://llm.test/v1",
        "llm_model": "test-model",
        "master_url": "http://master.test",
        "reuse_ttl_seconds": 3600,
        "ruleset_hash": _RULESET,
    }
    values.update(overrides)
    return AgentConfig(**values)


def _row(fp, verdict_id, at, level, verdict="TRUE_POSITIVE", **overrides):
    row = {
        "fp": fp,
        "verdict_id": verdict_id,
        "verdict": verdict,
        "explanation": f"explanation-{verdict_id}",
        "confidence_level": level,
        "evidence_basis": "direct_snippet" if level else None,
        "evidence_quote": "quote" if level else "",
        "quote_hash": "hash" if level else None,
        "prompt_sha256": "prompt",
        "ruleset_hash": _RULESET,
        "verdict_source": "model",
        "created_at": at,
        "at": at,
    }
    row.update(overrides)
    return row


async def _inventory(name, arguments):
    ids = ["fp-1", "fp-2", "fp-3", "fp-4", "fp-5"]
    return {
        "status": "ok",
        "project_id": "p1",
        "finding_ids": ids,
        "inventory_hash": "hash-1",
        "findings": [{"finding_id": fid} for fid in ids],
        "next_cursor": None,
        "total": len(ids),
    }


def test_reuse_selects_latest_and_marks_stale_revisions(tmp_path):
    rows = [
        _row("fp-1", "old", "2026-11-06T11:30:00Z", "medium", "FALSE_POSITIVE"),
        _row("fp-1", "fresh", "2026-11-06T11:45:00Z", "high"),
        _row("fp-2", "expired", "2026-11-06T10:00:00Z", "high"),
        _row("fp-3", "legacy", "2026-11-06T11:50:00Z", None),
        _row("fp-4", "invalid-date", "not-a-date", "medium"),
        _row("fp-5", "boundary", "2026-11-06T11:00:00Z", "medium"),
    ]
    for row in rows:
        row["prompt_sha256"] = _config(tmp_path).prompt_sha256_for_mode("sast")
    journaled = []

    async def master_call(name, arguments):
        return {"status": "ok", "rows": rows}

    async def journal(verdict):
        journaled.append(verdict)
        return verdict

    async def run():
        controller = AgentController(_inventory, journal=journal, master_call=master_call)
        await controller.initialize("full")
        stats = {}
        await reuse_prior_verdicts(_config(tmp_path), controller, stats, now=_NOW)
        await controller.execute(
            "submit_verdicts",
            {
                "verdicts": [
                    {
                        "finding_id": "fp-2",
                        "verdict": "NEEDS_REVIEW",
                        "explanation": "new evidence",
                        "confidence_level": "medium",
                        "evidence_basis": "indirect_pattern",
                    }
                ]
            },
        )
        return controller, stats

    controller, stats = asyncio.run(run())

    assert controller.verdicts["fp-1"].confidence_level == "high"
    assert controller.verdicts["fp-1"].evidence_basis == "direct_snippet"
    assert stats == {
        "reuse_candidates": 5,
        "reused_verdicts": 1,
        "reevaluated_verdicts": 4,
        "reevaluated_ttl_expired": 3,
        "reevaluated_legacy_confidence_missing": 1,
        "reevaluated_prompt_updated": 0,
        "reevaluated_ruleset_updated": 0,
        "human_verdicts_protected": 0,
        "reuse_ttl_seconds": 3600,
        "reuse_saved_tokens": None,
        "reuse_saved_tokens_known": False,
        "reuse_reasons": {
            "fresh_matching_context": 1,
            "ttl_expired": 3,
            "legacy_confidence_missing": 1,
        },
    }
    assert controller.revisions["fp-2"] == {
        "supersedes_verdict_id": "expired",
        "revision_reason": "ttl_expired",
    }
    assert controller.revisions["fp-3"]["revision_reason"] == "legacy_confidence_missing"
    assert len(journaled) == 1
    assert journaled[0].supersedes_verdict_id == "expired"
    assert journaled[0].revision_reason == "ttl_expired"
    reuse_actions = [
        item for item in controller.action_log if item["tool"] == "reuse_prior_verdicts"
    ]
    assert all(item["reuse_saved_tokens"] is None for item in reuse_actions)


def test_zero_ttl_reevaluates_even_fresh_confident_verdict(tmp_path):
    async def master_call(name, arguments):
        return {
            "status": "ok",
            "rows": [
                _row("fp-1", "fresh", "2026-11-06T11:59:00Z", "high")
                | {"prompt_sha256": _config(tmp_path).prompt_sha256_for_mode("sast")}
            ],
        }

    async def run():
        controller = AgentController(_inventory, master_call=master_call)
        await controller.initialize("full")
        stats = {}
        await reuse_prior_verdicts(
            _config(tmp_path, reuse_ttl_seconds=0), controller, stats, now=_NOW
        )
        return controller, stats

    controller, stats = asyncio.run(run())

    assert "fp-1" in controller.pending
    assert stats["reused_verdicts"] == 0
    assert stats["reevaluated_verdicts"] == 1


def test_disabled_reuse_does_not_query_master(tmp_path):
    async def master_call(name, arguments):
        raise AssertionError("master must not be queried")

    async def run():
        controller = AgentController(_inventory, master_call=master_call)
        await controller.initialize("full")
        stats = {}
        await reuse_prior_verdicts(
            _config(tmp_path, reuse_verdicts=False), controller, stats, now=_NOW
        )
        return controller, stats

    controller, stats = asyncio.run(run())

    assert len(controller.pending) == 5
    assert stats == {}


def test_prompt_hash_change_forces_prompt_updated_revision(tmp_path):
    async def master_call(name, arguments):
        return {
            "status": "ok",
            "rows": [_row("fp-1", "old-prompt", "2026-11-06T11:59:00Z", "high")],
        }

    async def run():
        controller = AgentController(_inventory, master_call=master_call)
        await controller.initialize("full")
        stats = {}
        await reuse_prior_verdicts(_config(tmp_path), controller, stats, now=_NOW)
        return controller, stats

    controller, stats = asyncio.run(run())

    assert stats["reused_verdicts"] == 0
    assert stats["reevaluated_prompt_updated"] == 1
    assert controller.revisions["fp-1"] == {
        "supersedes_verdict_id": "old-prompt",
        "revision_reason": "prompt_updated",
    }


def test_ruleset_change_forces_reevaluation_without_reuse(tmp_path):
    async def master_call(name, arguments):
        return {
            "status": "ok",
            "rows": [
                _row("fp-1", "old-rules", "2026-11-06T11:59:00Z", "high")
                | {
                    "prompt_sha256": _config(tmp_path).prompt_sha256_for_mode("sast"),
                    "ruleset_hash": "sha256:old-rules",
                }
            ],
        }

    async def run():
        controller = AgentController(_inventory, master_call=master_call)
        await controller.initialize("full")
        stats = {}
        await reuse_prior_verdicts(_config(tmp_path), controller, stats, now=_NOW)
        return controller, stats

    controller, stats = asyncio.run(run())

    assert stats["reused_verdicts"] == 0
    assert stats["reevaluated_ruleset_updated"] == 1
    assert stats["reuse_reasons"] == {"ruleset_updated": 1}
    assert controller.revisions["fp-1"] == {
        "supersedes_verdict_id": "old-rules",
        "revision_reason": "ruleset_updated",
    }


def test_missing_effective_ruleset_hash_disables_reuse(tmp_path):
    async def master_call(name, arguments):
        return {
            "status": "ok",
            "rows": [
                _row("fp-1", "unknown-rules", "2026-11-06T11:59:00Z", "high")
                | {"prompt_sha256": _config(tmp_path).prompt_sha256_for_mode("sast")}
            ],
        }

    async def run():
        controller = AgentController(_inventory, master_call=master_call)
        await controller.initialize("full")
        stats = {}
        await reuse_prior_verdicts(
            _config(tmp_path, ruleset_hash=None), controller, stats, now=_NOW
        )
        return controller, stats

    controller, stats = asyncio.run(run())

    assert stats["reused_verdicts"] == 0
    assert stats["reevaluated_ruleset_updated"] == 1
    assert controller.revisions["fp-1"]["revision_reason"] == "ruleset_updated"


def test_latest_human_verdict_is_protected_from_model_reuse_and_revision(tmp_path):
    async def master_call(name, arguments):
        return {
            "status": "ok",
            "rows": [
                _row(
                    "fp-1",
                    "human-verdict",
                    "2026-11-06T11:59:00Z",
                    "high",
                    verdict_source="human",
                )
                | {"prompt_sha256": _config(tmp_path).prompt_sha256_for_mode("sast")}
            ],
        }

    async def run():
        controller = AgentController(_inventory, master_call=master_call)
        await controller.initialize("full")
        stats = {}
        await reuse_prior_verdicts(_config(tmp_path), controller, stats, now=_NOW)
        return controller, stats

    controller, stats = asyncio.run(run())

    assert "fp-1" not in controller.pending
    assert "fp-1" not in controller.verdicts
    assert "fp-1" not in controller.revisions
    assert stats["reuse_candidates"] == 1
    assert stats["reused_verdicts"] == 0
    assert stats["human_verdicts_protected"] == 1
    assert stats["reuse_reasons"] == {"human_verdict": 1}
    reuse_actions = [
        item for item in controller.action_log if item["tool"] == "reuse_prior_verdicts"
    ]
    assert reuse_actions[0]["status"] == "protected"
