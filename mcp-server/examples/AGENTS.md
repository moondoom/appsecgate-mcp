# AppSecGate agent policy

Before reporting a coding task done:

1. Run `scan_diff` (or `scan_project` for a full review).
2. Call `check_gate(scope="diff", policy="block")` after fixes and verification.
   Use `scope="full"` after `scan_project`.
3. If `should_fail` is true and policy is `block`:
   - Do not mark the task done.
   - Report blocked findings with fingerprints and reasons.
4. If `recommended_action` is `verify_fix_batch`:
   - Call `verify_fix_batch` for `warned_fps` before reporting.
5. If `recommended_action` is `fix_blocked`:
   - Fix the blocked findings when edits are allowed, then rescan and check again.
   - Otherwise report the blockers without claiming completion.
6. If `recommended_action` is `report_only` or `escalate`:
   - Include the gate summary in the report or escalate it to a human.
7. Never suppress a finding without an explicit user request.

Agent-mode policy is advisory. Use the classic `appsecgate-mcp ci` hard-gate
for deterministic protected-merge and release enforcement.
