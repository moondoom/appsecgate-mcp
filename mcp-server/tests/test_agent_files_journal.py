from __future__ import annotations

import asyncio
import json

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.journal import TriageJournal
from appsecgate_mcp.agent.models import AgentConfig
from appsecgate_mcp.server.session import SessionState
from appsecgate_mcp.server.tools.files import _read_file


def test_read_project_file_returns_bounded_redacted_lines(tmp_path):
    (tmp_path / "app.py").write_text(
        'first = 1\ntoken = "AKIAIOSFODNN7EXAMPLE"\nthird = 3\nfourth = 4\n',
        encoding="utf-8",
    )
    state = SessionState()
    state.project_path = str(tmp_path)

    result = _read_file(state, path="app.py", start_line=2, end_line=3)

    assert result["status"] == "ok"
    assert [item["line"] for item in result["lines"]] == [2, 3]
    assert result["redacted"] is True
    assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(result)


def test_read_project_file_rejects_escape_sensitive_and_binary(tmp_path):
    state = SessionState()
    state.project_path = str(tmp_path)
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"a\x00b")
    (tmp_path / "inside.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "escape.txt").symlink_to(outside)

    assert _read_file(state, path="../escape", start_line=1, end_line=1)["status"] == "error"
    assert _read_file(state, path=".env", start_line=1, end_line=1)["status"] == "error"
    assert _read_file(state, path="binary.dat", start_line=1, end_line=1)["status"] == "error"
    assert _read_file(state, path="escape.txt", start_line=1, end_line=1)["status"] == "error"


async def _inventory_call(name, arguments):
    return {
        "status": "ok",
        "project_id": "p1",
        "finding_ids": ["fp-1"],
        "inventory_hash": "hash-1",
        "findings": [{"finding_id": "fp-1"}],
        "next_cursor": None,
        "total": 1,
    }


def test_triage_journal_redacts_and_deduplicates(tmp_path):
    config = AgentConfig(
        project=tmp_path,
        project_id="p1",
        data_dir=tmp_path / "data",
        run_id="run-1",
        llm_url="http://llm.test/v1",
        llm_model="test-model",
    )
    journal = TriageJournal(config)

    async def run():
        controller = AgentController(_inventory_call, journal=journal.append)
        await controller.initialize("full")
        arguments = {
            "verdicts": [
                {
                    "finding_id": "fp-1",
                    "verdict": "TRUE_POSITIVE",
                    "explanation": "token AKIAIOSFODNN7EXAMPLE",
                    "evidence": [{"file": "a.py", "note": "AKIAIOSFODNN7EXAMPLE"}],
                }
            ]
        }
        first = await controller._submit(arguments)
        second = await controller._submit(arguments)
        return first, second

    first, second = asyncio.run(run())
    lines = (tmp_path / "data" / "triage_verdicts.ndjson").read_text().splitlines()
    event = json.loads(lines[0])

    assert first["accepted"] == 1
    assert second["accepted"] == 0
    assert len(lines) == 1
    assert event["event_type"] == "triage_verdicted"
    assert event["project_key"] == "p1"
    assert event["verdict_source"] == "model"
    assert "AKIAIOSFODNN7EXAMPLE" not in lines[0]
