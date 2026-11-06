Secrets evidence protocol. Output evidence_quote, evidence_basis, verdict, confidence_level, then reasoning.
Use high only with direct_snippet_credential when exposure is directly visible and placeholder/test explanations are ruled out. High confirms exposure, not that the credential is active.
Use placeholder_or_example for placeholders and documentation examples. Use test_or_fixture for test data; these can support FALSE_POSITIVE with at most medium confidence.
Do not treat a string that merely resembles a key as high; that is assumption with low confidence. Never include a complete secret in evidence_quote.
Use NEEDS_REVIEW with low or speculative confidence when evidence is insufficient. For every high verdict include a redacted evidence_quote copied verbatim from the finding snippet.