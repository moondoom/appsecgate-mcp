from __future__ import annotations

import hashlib

import pytest

from appsecgate_mcp.agent.models import Verdict
from appsecgate_mcp.agent.verdict_validator import validate_verdict

_SNIPPET = "call site:\n    dangerous(input)\n    return value"


def _verdict(**overrides):
    values = {
        "finding_id": "fp-1",
        "verdict": "TRUE_POSITIVE",
        "confidence_level": "high",
        "evidence_basis": "direct_snippet",
        "evidence_quote": "dangerous(input)",
    }
    values.update(overrides)
    return Verdict(**values)


@pytest.mark.parametrize(
    ("mode", "basis"),
    [
        ("sast", "direct_snippet"),
        ("secrets", "direct_snippet_credential"),
        ("cve", "manifest_version_match"),
        ("iac", "policy_rule_direct"),
    ],
)
def test_mode_a_direct_basis_allows_high(mode, basis):
    result = validate_verdict(_verdict(evidence_basis=basis), mode, source_text=_SNIPPET)

    assert result.confidence_level == "high"
    assert result.model_confidence_level == "high"
    assert result.downgrade_reason is None
    assert result.quote_hash == hashlib.sha256(b"dangerous(input)").hexdigest()


def test_high_indirect_pattern_is_downgraded_with_model_preserved():
    result = validate_verdict(
        _verdict(evidence_basis="indirect_pattern"), "sast", source_text=_SNIPPET
    )

    assert result.confidence_level == "medium"
    assert result.model_confidence_level == "high"
    assert result.model_verdict == "TRUE_POSITIVE"
    assert result.downgrade_reason == "basis_not_high_capable"


def test_fp_without_positive_absence_evidence_becomes_needs_review():
    result = validate_verdict(_verdict(verdict="FALSE_POSITIVE"), "sast", source_text=_SNIPPET)

    assert result.verdict == "NEEDS_REVIEW"
    assert result.model_verdict == "FALSE_POSITIVE"
    assert result.downgrade_reason == "no_absence_evidence"


def test_high_with_quote_absent_from_source_is_downgraded():
    result = validate_verdict(_verdict(), "sast", source_text="unrelated code")

    assert result.confidence_level == "medium"
    assert result.downgrade_reason == "quote_mismatch"


def test_high_with_empty_quote_is_downgraded():
    result = validate_verdict(_verdict(evidence_quote=""), "sast", source_text=_SNIPPET)

    assert result.confidence_level == "medium"
    assert result.downgrade_reason == "quote_mismatch"


def test_high_quote_matches_source_after_whitespace_normalization():
    result = validate_verdict(
        _verdict(evidence_quote="dangerous(input)\nreturn value"), "sast", source_text=_SNIPPET
    )

    assert result.confidence_level == "high"
    assert result.downgrade_reason is None


def test_model_supplied_quote_hash_is_overwritten():
    result = validate_verdict(_verdict(quote_hash="0" * 64), "sast", source_text=_SNIPPET)

    assert result.quote_hash == hashlib.sha256(b"dangerous(input)").hexdigest()


def test_missing_basis_for_high_or_medium_is_protocol_error():
    with pytest.raises(ValueError, match="evidence_basis"):
        validate_verdict(_verdict(evidence_basis=None), "sast")


def test_fp_high_with_bad_quote_is_downgraded_before_verdict_override():
    result = validate_verdict(
        _verdict(verdict="FALSE_POSITIVE", evidence_quote=""), "sast", source_text=_SNIPPET
    )

    assert result.verdict == "NEEDS_REVIEW"
    assert result.confidence_level == "medium"
    assert result.downgrade_reason == "quote_mismatch"
