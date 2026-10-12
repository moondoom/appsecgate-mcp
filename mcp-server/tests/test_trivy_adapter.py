"""Тесты парсинга вывода Trivy без запуска бинарника."""

from __future__ import annotations

import json
from pathlib import Path

from appsecgate_mcp.scanners.trivy import TrivyAdapter


def _report(results: list[dict]) -> str:
    return json.dumps({"Results": results})


def test_vuln_target_is_normalized_and_message_redacted(tmp_path: Path) -> None:
    adapter = TrivyAdapter(project_path=str(tmp_path))
    stdout = _report(
        [
            {
                "Target": f"{tmp_path}/requirements.txt",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-2024-0001",
                        "PkgName": "requests",
                        "InstalledVersion": "2.0.0",
                        "FixedVersion": "2.31.0",
                        "Severity": "HIGH",
                        "Title": f"issue in {tmp_path}/requirements.txt",
                    }
                ],
            }
        ]
    )
    findings = adapter._parse(stdout)
    assert len(findings) == 1
    assert findings[0].file_path == "requirements.txt"
    assert str(tmp_path) not in findings[0].message


def test_license_file_path_is_normalized(tmp_path: Path) -> None:
    adapter = TrivyAdapter(project_path=str(tmp_path))
    stdout = _report(
        [
            {
                "Target": "package-lock.json",
                "Licenses": [
                    {
                        "Name": "MIT",
                        "FilePath": f"{tmp_path}/node_modules/x/LICENSE",
                        "Severity": "LOW",
                        "Category": "notice",
                    }
                ],
            }
        ]
    )
    findings = adapter._parse(stdout)
    assert len(findings) == 1
    assert findings[0].file_path == "node_modules/x/LICENSE"


def test_misconfig_relative_target_keeps_lines(tmp_path: Path) -> None:
    adapter = TrivyAdapter(project_path=str(tmp_path))
    stdout = _report(
        [
            {
                "Target": "Dockerfile",
                "Misconfigurations": [
                    {
                        "ID": "DS002",
                        "Severity": "HIGH",
                        "Message": "root user",
                        "Title": "root user",
                        "CauseMetadata": {"StartLine": 2, "EndLine": 2},
                    }
                ],
            }
        ]
    )
    findings = adapter._parse(stdout)
    assert len(findings) == 1
    assert findings[0].file_path == "Dockerfile"
    assert findings[0].line_start == 2


def test_empty_and_invalid_output(tmp_path: Path) -> None:
    adapter = TrivyAdapter(project_path=str(tmp_path))
    assert adapter._parse("") == []
    assert adapter._parse("not json") == []
    assert adapter._parse("{}") == []
