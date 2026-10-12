"""Тесты парсинга вывода сканеров (без запуска бинарников)."""

from __future__ import annotations

import json

from appsecgate_mcp.models.finding import Category
from appsecgate_mcp.scanners.gitleaks import GitleaksAdapter
from appsecgate_mcp.scanners.semgrep import SemgrepAdapter
from appsecgate_mcp.scanners.trivy import TrivyAdapter
from appsecgate_mcp.scanners.trufflehog import TruffleHogAdapter


class TestSemgrepParse:
    def test_parses_results(self):
        payload = {
            "results": [
                {
                    "check_id": "python.lang.security.audit.exec",
                    "path": "app.py",
                    "start": {"line": 3},
                    "end": {"line": 4},
                    "extra": {
                        "severity": "ERROR",
                        "message": "exec used",
                        "lines": "exec(x)",
                        "metadata": {"cwe": "CWE-78"},
                    },
                }
            ]
        }
        findings = SemgrepAdapter()._parse(json.dumps(payload))
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "python.lang.security.audit.exec"
        assert f.raw_severity == "ERROR"
        assert f.category is Category.SAST
        assert f.line_start == 3 and f.line_end == 4

    def test_metadata_patch_from_fix(self):
        payload = {
            "results": [
                {
                    "check_id": "python.lang.security.audit.exec",
                    "path": "app.py",
                    "start": {"line": 3},
                    "end": {"line": 4},
                    "extra": {
                        "severity": "ERROR",
                        "message": "exec used",
                        "lines": "exec(x)",
                        "metadata": {"fix": "subprocess.run(...)"},
                    },
                }
            ]
        }
        findings = SemgrepAdapter()._parse(json.dumps(payload))
        assert len(findings) == 1
        assert findings[0].metadata["patch"] == "subprocess.run(...)"

    def test_metadata_patch_none_without_fix(self):
        payload = {
            "results": [
                {
                    "check_id": "python.lang.security.audit.exec",
                    "path": "app.py",
                    "start": {"line": 3},
                    "end": {"line": 4},
                    "extra": {
                        "severity": "ERROR",
                        "message": "exec used",
                        "lines": "exec(x)",
                        "metadata": {},
                    },
                }
            ]
        }
        findings = SemgrepAdapter()._parse(json.dumps(payload))
        assert len(findings) == 1
        assert findings[0].metadata["patch"] is None

    def test_bad_json_returns_empty(self):
        assert SemgrepAdapter()._parse("not json") == []


class TestGitleaksParse:
    def test_parses_array(self):
        payload = [
            {
                "RuleID": "aws-access-token",
                "File": "config.py",
                "StartLine": 10,
                "EndLine": 10,
                "Description": "AWS key",
                "Match": "AKIA...",
            }
        ]
        findings = GitleaksAdapter()._parse(json.dumps(payload))
        assert len(findings) == 1
        assert findings[0].category is Category.SECRET
        assert findings[0].raw_severity == "high"

    def test_object_returns_empty(self):
        assert GitleaksAdapter()._parse(json.dumps({"a": 1})) == []


class TestTruffleHogParse:
    def test_parses_jsonl(self):
        line = json.dumps(
            {
                "DetectorName": "AWS",
                "Verified": True,
                "Raw": "AKIA...",
                "SourceMetadata": {"Data": {"Filesystem": {"file": "a.py", "line": 7}}},
            }
        )
        findings = TruffleHogAdapter()._parse(line + "\n" + "{bad json}\n")
        assert len(findings) == 1
        assert findings[0].raw_severity == "high"  # verified
        assert findings[0].line_start == 7

    def test_unverified_is_medium(self):
        line = json.dumps({"DetectorName": "X", "Verified": False})
        findings = TruffleHogAdapter()._parse(line)
        assert findings[0].raw_severity == "medium"


class TestTrivyParse:
    def test_parses_vulns_misconfigs_licenses(self):
        payload = {
            "Results": [
                {
                    "Target": "requirements.txt",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-1",
                            "Severity": "HIGH",
                            "PkgName": "requests",
                            "FixedVersion": "2.31.0",
                        }
                    ],
                    "Misconfigurations": [
                        {
                            "ID": "DS002",
                            "Severity": "MEDIUM",
                            "Message": "root user",
                            "CauseMetadata": {"StartLine": 1, "EndLine": 1},
                        }
                    ],
                    "Licenses": [{"Name": "GPL-3.0", "Severity": "LOW", "Category": "restricted"}],
                }
            ]
        }
        findings = TrivyAdapter()._parse(json.dumps(payload))
        categories = {f.category for f in findings}
        assert categories == {Category.SCA, Category.IAC, Category.LICENSE}
        assert len(findings) == 3
