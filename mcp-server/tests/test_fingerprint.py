"""Тесты FingerprintGenerator: стабильность и чувствительность."""

from __future__ import annotations

from appsecgate_mcp.normalization.fingerprint import (
    FingerprintGenerator,
    normalize_snippet,
)


class TestNormalizeSnippet:
    def test_empty(self):
        assert normalize_snippet("") == ""

    def test_strips_comments_and_collapses_whitespace(self):
        raw = "  password = 'x'  # inline comment\n\n"
        assert normalize_snippet(raw) == "password = 'x'"

    def test_case_insensitive(self):
        assert normalize_snippet("PASSWORD = X") == normalize_snippet("password = x")


class TestFingerprint:
    def test_stable_regardless_of_line(self):
        gen = FingerprintGenerator()
        fp1 = gen.generate_for("rule", "a.py", "x = 1")
        fp2 = gen.generate_for("rule", "a.py", "x = 1")
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_differs_by_file(self):
        gen = FingerprintGenerator()
        assert gen.generate_for("r", "a.py", "x") != gen.generate_for("r", "b.py", "x")

    def test_differs_by_rule(self):
        gen = FingerprintGenerator()
        assert gen.generate_for("r1", "a.py", "x") != gen.generate_for("r2", "a.py", "x")

    def test_snippet_normalized_in_hash(self):
        gen = FingerprintGenerator()
        fp1 = gen.generate_for("r", "a.py", "x = 1  # c")
        fp2 = gen.generate_for("r", "a.py", "x = 1")
        assert fp1 == fp2
