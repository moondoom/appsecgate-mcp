from __future__ import annotations

from appsecgate_mcp.agent.cli import agent_main


def test_empty_knowledge_cutoff_means_no_cutoff(monkeypatch, tmp_path, capsys):
    captured = {}

    async def fake_run(config):
        captured["knowledge_cutoff"] = config.knowledge_cutoff
        return {
            "run_id": config.run_id,
            "mode": "ro",
            "model": "test-model",
            "findings": [],
            "verdicts": [],
            "patches": [],
            "GateSummary": {"should_fail": False},
            "action_log": [],
            "usage": {},
            "warnings": [],
            "exit_reason": "report_generated",
        }

    monkeypatch.setattr("appsecgate_mcp.agent.cli.run_agent", fake_run)
    monkeypatch.setenv("APPSECGATE_KNOWLEDGE_CUTOFF", "")

    result = agent_main(
        [
            "--project",
            str(tmp_path),
            "--data-dir",
            str(tmp_path / "data"),
            "--llm-url",
            "http://llm.test/v1",
            "--llm-model",
            "test-model",
            "--no-sync",
            "--output-format",
            "json",
        ]
    )

    assert result == 0
    assert captured["knowledge_cutoff"] is None
