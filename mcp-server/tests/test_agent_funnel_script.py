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
