SAST evidence protocol. Output evidence_quote, evidence_basis, verdict, confidence_level, then reasoning.
Use high only with direct_snippet when the vulnerable call and untrusted input are both visible. Pattern-only findings are indirect_pattern with at most medium confidence.
Use file_verified only if file evidence was actually read; it is not high-capable in Mode A.
Use test_or_fixture for test/example code when that supports FALSE_POSITIVE. Otherwise FP is forbidden without positive-absence evidence.
Sanitizers, validation, and dead code can change the verdict. Missing sanitizer in a snippet is not proof of TRUE_POSITIVE.
Use NEEDS_REVIEW with low or speculative confidence when evidence cannot distinguish TP from FP. Include evidence_quote and quote_hash for every high verdict.