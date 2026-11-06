from __future__ import annotations

from appsecgate_master.contracts.events import MasterEvent

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


def edge_validation_error(event: MasterEvent) -> str | None:
    if event.confidence_level is None and event.evidence_basis is None:
        return None
    mode = event.prompt_mode or "sast"
    if event.confidence_level in {"high", "medium"} and event.evidence_basis is None:
        return "missing_evidence_basis"
    if event.confidence_level == "high":
        if event.evidence_basis not in _HIGH_BASIS[mode]:
            return "basis_not_high_capable"
        if not event.evidence_quote or not event.quote_hash or len(event.quote_hash) != 64:
            return "quote_mismatch"
        if any(char not in "0123456789abcdef" for char in event.quote_hash):
            return "quote_mismatch"
    if event.verdict == "FALSE_POSITIVE" and (
        event.confidence_level == "speculative"
        or event.evidence_basis not in _FP_BASIS[mode]
        or (mode == "cve" and event.confidence_level == "low")
    ):
        return "no_absence_evidence"
    return None
