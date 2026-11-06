from __future__ import annotations

import hashlib

from appsecgate_mcp.agent.models import Verdict

_HIGH_BASIS = {
    "sast": {"direct_snippet"},
    "secrets": {"direct_snippet_credential"},
    "cve": {"manifest_version_match", "vex_upstream", "manifest_absent"},
    "iac": {"policy_rule_direct", "deployment_verified"},
}
_FP_BASIS = {
    "sast": {"file_verified", "test_or_fixture"},
    "secrets": {"file_verified", "placeholder_or_example", "test_or_fixture"},
    "cve": {"manifest_absent", "vex_upstream"},
    "iac": {"policy_rule_context", "override_possible"},
}


def finding_mode(category: str | None) -> str:
    return {"secret": "secrets", "sca": "cve", "iac": "iac"}.get(category or "", "sast")


def validate_verdict(verdict: Verdict, mode: str) -> Verdict:
    if verdict.confidence_level is None and verdict.evidence_basis is None:
        return verdict
    if verdict.confidence_level in {"high", "medium"} and verdict.evidence_basis is None:
        raise ValueError("evidence_basis is required for high/medium confidence")
    validated = verdict.model_copy(
        update={
            "model_confidence_level": verdict.confidence_level,
            "model_verdict": verdict.verdict,
        }
    )
    if validated.confidence_level == "high":
        expected_hash = hashlib.sha256(validated.evidence_quote.encode()).hexdigest()
        if validated.evidence_basis not in _HIGH_BASIS[mode]:
            validated = validated.model_copy(
                update={
                    "confidence_level": "medium",
                    "downgrade_reason": "basis_not_high_capable",
                }
            )
        elif not validated.evidence_quote.strip() or validated.quote_hash != expected_hash:
            validated = validated.model_copy(
                update={"confidence_level": "medium", "downgrade_reason": "quote_mismatch"}
            )
    if validated.verdict == "FALSE_POSITIVE" and (
        validated.confidence_level == "speculative"
        or validated.evidence_basis not in _FP_BASIS[mode]
        or (mode == "cve" and validated.confidence_level == "low")
    ):
        return validated.model_copy(
            update={
                "verdict": "NEEDS_REVIEW",
                "downgrade_reason": validated.downgrade_reason or "no_absence_evidence",
            }
        )
    return validated
