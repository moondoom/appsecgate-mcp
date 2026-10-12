"""Тесты парсинга вывода Gitleaks без запуска бинарника."""

from __future__ import annotations

import json
from pathlib import Path

from appsecgate_mcp.scanners.gitleaks import GitleaksAdapter


def _report(items: list[dict]) -> str:
    return json.dumps(items)


def test_parse_normalizes_absolute_file_path(tmp_path: Path) -> None:
    adapter = GitleaksAdapter(project_path=str(tmp_path))
    stdout = _report(
        [
            {
                "RuleID": "aws-access-token",
                "File": f"{tmp_path}/src/app.py",
                "StartLine": 3,
                "EndLine": 3,
                "Match": "AKIA...",
            }
        ]
    )
    findings = adapter._parse(stdout)
    assert len(findings) == 1
    assert findings[0].file_path == "src/app.py"


def test_parse_redacts_root_in_fingerprint(tmp_path: Path) -> None:
    adapter = GitleaksAdapter(project_path=str(tmp_path))
    stdout = _report(
        [
            {
                "RuleID": "aws-access-token",
                "File": f"{tmp_path}/src/app.py",
                "StartLine": 3,
                "Fingerprint": f"abc123:{tmp_path}/src/app.py:aws-access-token:3",
            }
        ]
    )
    findings = adapter._parse(stdout)
    fingerprint = findings[0].metadata["fingerprint"]
    assert str(tmp_path) not in fingerprint
    assert fingerprint == "abc123:src/app.py:aws-access-token:3"


def test_parse_missing_fingerprint_is_none(tmp_path: Path) -> None:
    adapter = GitleaksAdapter(project_path=str(tmp_path))
    stdout = _report([{"RuleID": "generic", "File": "a.env", "StartLine": 1}])
    findings = adapter._parse(stdout)
    assert findings[0].metadata["fingerprint"] is None
    assert findings[0].file_path == "a.env"


def test_parse_empty_and_invalid_output(tmp_path: Path) -> None:
    adapter = GitleaksAdapter(project_path=str(tmp_path))
    assert adapter._parse("") == []
    assert adapter._parse("not json") == []
    assert adapter._parse("{}") == []
