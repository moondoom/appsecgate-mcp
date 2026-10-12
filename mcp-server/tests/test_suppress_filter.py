"""Тесты ConfigSuppressFilter: rule (подстрока), paths (glob c `**`), пустой paths.

Также интеграционный тест, что фильтр в `ScanCoordinator.scan()` срабатывает
после dedup и до попадания находок в результат.
"""

from __future__ import annotations

import pytest

from appsecgate_mcp.config.models import Config, SuppressRuleConfig
from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.normalization.suppress_filter import ConfigSuppressFilter, _glob_match
from appsecgate_mcp.orchestration.coordinator import ScanCoordinator
from appsecgate_mcp.scanners.base import BaseScanner, RawFinding
from appsecgate_mcp.scanners.registry import ScannerRegistry


def finding(rule_id: str, file_path: str = "src/app.py") -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=Severity.HIGH,
        file_path=file_path,
        scanner="semgrep",
        category=Category.SAST,
        snippet="x = 1",
    )


def config_with(*rules: SuppressRuleConfig) -> Config:
    config = Config(suppress=list(rules))
    return config


# --- _glob_match ---


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("tests/test_a.py", "tests/**", True),
        ("tests/nested/deep/test_b.py", "tests/**", True),
        ("src/app.py", "tests/**", False),
        ("examples/foo.py", "examples/*.py", True),
        ("examples/sub/foo.py", "examples/*.py", False),
        ("examples/foo.py", "examples/**", True),
        ("examples/sub/foo.py", "examples/**", True),
        ("tests/a.py", "**/*.py", True),
        ("tests/nested/a.py", "**/*.py", True),
        ("app.js", "**/*.py", False),
    ],
)
def test_glob_match(path, pattern, expected):
    assert _glob_match(path, pattern) is expected


# --- ConfigSuppressFilter.apply ---


def test_rule_substring_suppresses():
    filt = ConfigSuppressFilter(config_with(SuppressRuleConfig(rule="generic.secrets")))
    result = filt.apply([finding("semgrep.generic.secrets")])
    assert result == []


def test_rule_substring_keeps_non_matching():
    filt = ConfigSuppressFilter(config_with(SuppressRuleConfig(rule="generic.secrets")))
    result = filt.apply([finding("semgrep.generic.aws.api-key")])
    assert len(result) == 1


def test_rule_matching_is_case_sensitive():
    filt = ConfigSuppressFilter(config_with(SuppressRuleConfig(rule="Secrets")))
    assert len(filt.apply([finding("semgrep.generic.secrets")])) == 1


def test_paths_glob_scopes_rule():
    filt = ConfigSuppressFilter(config_with(SuppressRuleConfig(rule="secrets", paths=["tests/**"])))
    findings = [
        finding("semgrep.generic.secrets", "tests/x.py"),
        finding("semgrep.generic.secrets", "src/app.py"),
    ]
    result = filt.apply(findings)
    assert [f.file_path for f in result] == ["src/app.py"]


def test_empty_paths_applies_to_all_files():
    filt = ConfigSuppressFilter(config_with(SuppressRuleConfig(rule="secrets")))
    assert filt.apply([finding("semgrep.generic.secrets", "anywhere/here.py")]) == []


def test_empty_rule_never_suppresses():
    filt = ConfigSuppressFilter(config_with(SuppressRuleConfig(rule="", paths=["**"])))
    assert len(filt.apply([finding("semgrep.generic.secrets")])) == 1


def test_no_suppress_rules_passthrough():
    filt = ConfigSuppressFilter(config_with())
    original = [finding("semgrep.generic.secrets")]
    assert filt.apply(original) == original


# --- Интеграция с ScanCoordinator ---


class FakeScanner(BaseScanner):
    name = "fake"

    def __init__(self, findings, **kw):
        super().__init__(**kw)
        self._findings = findings

    async def is_available(self) -> bool:
        return True

    async def scan(self, files, mode):
        return list(self._findings)


def rf(rule_id: str, file_path: str) -> RawFinding:
    return RawFinding(
        rule_id=rule_id,
        raw_severity="high",
        file_path=file_path,
        scanner="fake",
        snippet="x = 1",
        category=Category.SAST,
    )


@pytest.mark.asyncio
async def test_coordinator_filters_suppressed():
    config = Config(suppress=[SuppressRuleConfig(rule="secrets", paths=["tests/**"])])
    registry = ScannerRegistry()
    registry.register(
        FakeScanner(
            [
                rf("semgrep.generic.secrets", "tests/x.py"),
                rf("semgrep.generic.secrets", "src/app.py"),
            ]
        )
    )
    coord = ScanCoordinator(config, registry)
    result = await coord.scan(["tests/x.py", "src/app.py"])
    assert [f.file_path for f in result.findings] == ["src/app.py"]
