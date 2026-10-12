"""Тесты Deduplicator и Normalizer."""

from __future__ import annotations

from appsecgate_mcp.config.models import Config
from appsecgate_mcp.models.finding import Category, Finding, Severity
from appsecgate_mcp.normalization.dedup import Deduplicator
from appsecgate_mcp.normalization.normalizer import Normalizer, normalize_severity


def make_finding(**kwargs) -> Finding:
    base = dict(
        fingerprint="fp",
        rule_id="rule",
        severity=Severity.HIGH,
        file_path="a.py",
        line_start=1,
        scanner="semgrep",
        category=Category.SAST,
    )
    base.update(kwargs)
    return Finding(**base)


class TestNormalizeSeverity:
    def test_known_values(self):
        assert normalize_severity("CRITICAL") is Severity.CRITICAL
        assert normalize_severity("High") is Severity.HIGH
        assert normalize_severity("ERROR") is Severity.HIGH

    def test_unknown_falls_back_to_info(self):
        assert normalize_severity("bogus") is Severity.INFO
        assert normalize_severity("") is Severity.INFO


class TestDeduplicator:
    def test_same_file_and_line_collapses(self):
        a = make_finding(scanner="gitleaks", fingerprint="a")
        b = make_finding(scanner="trufflehog", fingerprint="b")
        result = Deduplicator().deduplicate([a, b])
        assert len(result) == 1

    def test_different_lines_kept(self):
        a = make_finding(line_start=1, fingerprint="a")
        b = make_finding(line_start=2, fingerprint="b")
        assert len(Deduplicator().deduplicate([a, b])) == 2

    def test_higher_severity_wins(self):
        a = make_finding(severity=Severity.LOW, scanner="gitleaks", fingerprint="a")
        b = make_finding(severity=Severity.CRITICAL, scanner="trufflehog", fingerprint="b")
        result = Deduplicator().deduplicate([a, b])
        assert len(result) == 1
        assert result[0].severity is Severity.CRITICAL
        assert result[0].scanner == "trufflehog"

    def test_equal_severity_keeps_first(self):
        a = make_finding(severity=Severity.HIGH, scanner="gitleaks", fingerprint="a")
        b = make_finding(severity=Severity.HIGH, scanner="trufflehog", fingerprint="b")
        result = Deduplicator().deduplicate([a, b])
        assert len(result) == 1
        assert result[0].scanner == "gitleaks"


class TestNormalizer:
    def test_threshold_filters_low(self):
        config = Config()
        normalizer = Normalizer(config)
        findings = [
            make_finding(severity=Severity.CRITICAL, fingerprint="c"),
            make_finding(severity=Severity.INFO, fingerprint="i"),
        ]
        result = normalizer.process(findings)
        assert [f.fingerprint for f in result] == ["c"]

    def test_sorted_by_severity_desc(self):
        config = Config()
        normalizer = Normalizer(config)
        findings = [
            make_finding(severity=Severity.MEDIUM, fingerprint="m"),
            make_finding(severity=Severity.HIGH, fingerprint="h"),
        ]
        result = normalizer.process(findings)
        assert result[0].fingerprint == "h"
