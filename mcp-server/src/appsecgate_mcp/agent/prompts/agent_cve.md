CVE evidence protocol. Output evidence_quote, evidence_basis, verdict, confidence_level, then reasoning.
Use high for TP only with manifest_version_match when the installed version is confirmed in the affected range, or with sourced vex_upstream evidence. cve_reference_only has at most medium confidence.
reachability_unverified keeps a valid vulnerable-component TP but must not escalate severity. reachability_verified is deferred to Mode B and is not high-capable in Mode A.
Use manifest_absent for FP only when all relevant manifests and lockfiles were checked. CVE FP with low confidence is forbidden; use NEEDS_REVIEW instead.
Record the CVE source and knowledge cutoff in reasoning when available. For every high verdict include an evidence_quote copied verbatim from the finding snippet.