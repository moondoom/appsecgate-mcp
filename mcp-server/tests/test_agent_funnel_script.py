from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _collector():
    path = (
        Path(__file__).resolve().parents[2] / "experiments" / "tp-0001" / "collect_agent_funnel.py"
    )
    spec = importlib.util.spec_from_file_location("collect_agent_funnel", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collect_agent_funnel_includes_missing_and_preserves_review(monkeypatch, tmp_path):
    module = _collector()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    run_dir = tmp_path / "artifacts" / "asgfree300-gemmaq3-p4-repo"
    run_dir.mkdir(parents=True)
    report = {
        "run_id": "asgfree300-gemmaq3-p4-repo",
        "scan_meta": {
            "scanner_raw": 4,
            "in_scope": 4,
            "dedup_level1": 3,
            "dedup_level2": 2,
            "suppressed": 0,
            "eligible": 2,
        },
        "inventory": {"total": 2, "hash": "hash-1", "missing_ids": ["fp-2"]},
        "findings": [
            {"finding_id": "fp-1", "rule_id": "rule-1"},
            {"finding_id": "fp-2", "rule_id": "rule-2"},
        ],
        "verdicts": [
            {
                "finding_id": "fp-1",
                "verdict": "FALSE_POSITIVE",
                "explanation": "example",
                "evidence": [],
            }
        ],
        "usage": {},
    }
    (run_dir / "report.json").write_text(json.dumps(report))
    monkeypatch.setattr("sys.argv", ["collect_agent_funnel.py", "--label", "asgfree300"])

    module.main()

    funnel = json.loads((tmp_path / "artifacts" / "asgfree300-funnel.json").read_text())
    review_path = tmp_path / "artifacts" / "asgfree300-review.json"
    review = json.loads(review_path.read_text())
    assert funnel["totals"]["scanner_raw"] == 4
    assert funnel["totals"]["dedup_level2"] == 2
    assert funnel["totals"]["model_fp"] == 1
    assert funnel["totals"]["missing"] == 1
    assert review[1]["model_verdict"] is None

    review[0]["human_verdict"] = "FALSE_POSITIVE"
    review[0]["reviewer"] = "reviewer-1"
    review_path.write_text(json.dumps(review))
    module.main()
    regenerated = json.loads(review_path.read_text())
    assert regenerated[0]["human_verdict"] == "FALSE_POSITIVE"
    assert regenerated[0]["reviewer"] == "reviewer-1"


def _benchmark():
    path = Path(__file__).resolve().parents[2] / "experiments" / "tp-0001" / "benchmark_parallel.py"
    spec = importlib.util.spec_from_file_location("benchmark_parallel", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repeat_artifacts_can_use_baseline_project_identity(monkeypatch):
    module = _benchmark()
    monkeypatch.setenv("BENCH_LABEL", "agent300repeat")
    monkeypatch.setenv("BENCH_PROJECT_ID_LABEL", "agent300")
    monkeypatch.delenv("APPSECGATE_PROJECT_ID", raising=False)

    project_id = module.project_id_for("CodeWiki", "agent300repeat-gemmaq3-p1-CodeWiki")

    assert project_id == "CodeWiki-tp0001-agent300-gemmaq3-p1-CodeWiki"


def _reevaluation_collector():
    path = (
        Path(__file__).resolve().parents[2]
        / "experiments"
        / "tp-0001"
        / "collect_reevaluation_stats.py"
    )
    spec = importlib.util.spec_from_file_location("collect_reevaluation_stats", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reevaluation_stats_cover_confidence_drift_and_provenance(monkeypatch, tmp_path):
    module = _reevaluation_collector()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    (tmp_path / "artifacts").mkdir()
    (artifacts / "agent300-run-config.json").write_text('{"repeat": ["repo"]}')
    run_id = f"{module.LABEL}-gemmaq3-p1-repo"
    report_dir = artifacts / run_id
    report_dir.mkdir(parents=True)
    report = {
        "exit_reason": "report_generated",
        "inventory": {"total": 2, "missing_ids": []},
        "findings": [
            {"finding_id": "fp-1", "rule_id": "rule-1"},
            {"finding_id": "fp-2", "rule_id": "rule-2"},
        ],
        "verdicts": [
            {"finding_id": "fp-1", "verdict": "TRUE_POSITIVE", "confidence": 90},
            {"finding_id": "fp-2", "verdict": "NEEDS_REVIEW", "confidence": 40},
        ],
        "usage": {
            "reused_verdicts": 1,
            "reevaluated_verdicts": 1,
            "reevaluated_legacy_confidence_missing": 1,
            "failed_findings": 0,
            "missing": 0,
        },
    }
    (report_dir / "report.json").write_text(json.dumps(report))
    baseline_dir = artifacts / "agent300-gemmaq3-p1-repo"
    baseline_dir.mkdir()
    baseline = {"verdicts": [{"finding_id": "fp-1", "verdict": "NEEDS_REVIEW"}]}
    (baseline_dir / "report.json").write_text(json.dumps(baseline))
    journal_dir = tmp_path / "runtime" / f"data-{run_id}"
    journal_dir.mkdir(parents=True)
    event = {
        "supersedes_verdict_id": "old",
        **dict.fromkeys(
            ["actor_id", "model", "prompt_sha256", "ruleset_hash", "rule_hash_status"], "x"
        ),
    }
    (journal_dir / "triage_verdicts.ndjson").write_text(json.dumps(event) + "\n")

    result = module.collect()

    assert result["aggregate"]["complete_runs"] == 1
    assert result["aggregate"]["confidence"]["bands"] == {"0-49": 1, "80-100": 1}
    assert result["aggregate"]["verdict_drift"] == 1
    assert result["aggregate"]["complete_provenance"] == 1
    assert result["transitions"][0]["after"] == "TRUE_POSITIVE"


def _rev1_validator():
    path = Path(__file__).resolve().parents[2] / "experiments" / "tp-0001" / "validate_rev1.py"
    spec = importlib.util.spec_from_file_location("validate_rev1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _phase_report(fp, verdict="TRUE_POSITIVE", confidence=90, **usage):
    return {
        "exit_reason": "report_generated",
        "findings": [{"finding_id": fp}],
        "verdicts": [{"finding_id": fp, "verdict": verdict, "confidence": confidence}],
        "usage": {
            "reuse_candidates": 1,
            "reused_verdicts": 1,
            "reevaluated_verdicts": 0,
            "failed_findings": 0,
            **usage,
        },
    }


def test_rev1_fresh_gate_requires_zero_llm_and_events(monkeypatch, tmp_path):
    module = _rev1_validator()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    before = {project: _phase_report(f"fp-{project}") for project in module.PROJECTS}

    counts = {project: 1 for project in module.PROJECTS}
    assert module._fresh_errors(before, before, counts, counts) == []


def test_rev1_revision_gate_checks_reason_and_supersedes(monkeypatch, tmp_path):
    module = _rev1_validator()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    report = _phase_report("fp-1", reused_verdicts=0, reevaluated_verdicts=1)
    report_dir = tmp_path / "artifacts" / "rev1-b-gemmaq3-p1-structlog"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text(json.dumps(report))
    event = {
        "fp": "fp-1",
        "revision_reason": "ttl_expired",
        "supersedes_verdict_id": "old",
        "confidence": 90,
        "ruleset_hash": "sha256:rules",
    }
    journal_dir = tmp_path / "runtime" / "data-rev1-b-gemmaq3-p1-structlog"
    journal_dir.mkdir(parents=True)
    (journal_dir / "triage_verdicts.ndjson").write_text(json.dumps(event) + "\n")

    assert module._revision_errors("rev1-b", "structlog", "ttl_expired", {"fp-1": "old"}) == []


def test_rev1_legacy_seed_is_append_only_and_omits_confidence(monkeypatch, tmp_path):
    module = _rev1_validator()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    report = _phase_report("fp-1")
    report["scan_meta"] = {"ruleset_hash": "sha256:rules"}
    report["findings"][0].update(
        scanner="semgrep", rule_id="rule-1", rule_hash_status="definition_sha256"
    )
    report_dir = tmp_path / "artifacts" / "rev1-a1-gemmaq3-p1-aitextgen"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text(json.dumps(report))
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "agent300-keys.json").write_text(
        json.dumps({module._project_key("aitextgen"): "key"})
    )
    (tmp_path / "artifacts" / "agent300-run-config.json").write_text(
        json.dumps({"master": {"host_url": "http://master.test"}})
    )
    captured = {}

    def request(path, project, *, payload=None):
        captured.update(path=path, project=project, payload=payload)
        return {"outcomes": [{"outcome": "accepted"}]}

    monkeypatch.setattr(module, "_master_request", request)

    module._legacy_seed()

    event = captured["payload"]["events"][0]
    assert captured["path"] == "/v1/events"
    assert "confidence" not in event
    assert event["actor_id"] == "legacy-seed"
    assert event["verdict_id"] == event["client_event_id"]
