from __future__ import annotations

from appsecgate_mcp.agent.cli import agent_main


def test_agent_reads_guided_execution_parameters(monkeypatch, tmp_path):
    captured = {}

    async def fake_run(config):
        captured.update(
            agent_mode=config.agent_mode,
            internal_parallel=config.internal_parallel,
            batch_sort=config.batch_sort,
            llm_failure_timeout=config.llm_failure_timeout,
        )
        return {
            "run_id": config.run_id,
            "mode": "ro",
            "model": config.llm_model,
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
    monkeypatch.setenv("APPSECGATE_AGENT_INTERNAL_PARALLEL", "2")
    monkeypatch.setenv("APPSECGATE_AGENT_BATCH_SORT", "none")
    monkeypatch.setenv("APPSECGATE_LLM_FAILURE_TIMEOUT_S", "600")

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
    assert captured == {
        "agent_mode": "guided",
        "internal_parallel": 2,
        "batch_sort": "none",
        "llm_failure_timeout": 600,
    }


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
