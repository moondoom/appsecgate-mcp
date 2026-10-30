"""FastMCP-инстанс сервера AppSecGate."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "appsecgate-mcp",
    instructions=(
        "AppSecGate is a security scanner. The server finds, stores, and verifies "
        "findings. The server does NOT generate or apply fixes — the agent does "
        "that with its own LLM.\n\n"
        "Fix protocol:\n"
        "1. After Edit/Write, call scan_file(path).\n"
        "2. For each finding, call get_fix_context(finding_id). For a group, use "
        "get_fix_context_batch(finding_ids=[...]).\n"
        "3. Generate a fix with your LLM. Apply it via Edit/Write.\n"
        "4. After applying, call verify_fix(...) or verify_fix_batch([...]). "
        "The server rescans files and confirms the result.\n"
        "5. If verified=false, the finding is NOT fixed. Retry or mark wont_fix "
        "with a note.\n\n"
        "Bulk queries:\n"
        "- scan_project returns a summary only (announce). For details use "
        "query_findings_db with SQL over views.\n"
        "- Available views: v_findings, v_attempts, v_summary, "
        "v_verification_coverage, v_projects. SELECT only.\n"
        "- The server adds the current-project filter (project_id) and a "
        "LIMIT 1000 automatically. Do NOT add project_id predicates to the "
        "SQL and do not guess project ids; WHERE/GROUP BY/ORDER BY/HAVING for "
        "the analysis are fine, e.g. "
        "\"SELECT severity, COUNT(*) AS n FROM v_findings WHERE status = 'SHOWN' "
        'GROUP BY severity ORDER BY n DESC".\n\n'
        "Constraints:\n"
        "- Do not edit files outside finding.file_path.\n"
        "- Do not delete secrets from code — suggest rotation via submit_feedback.\n"
        "- Redacted fields are placeholders; do not attempt to recover them.\n"
        "- All work is scoped to the current project (project_id)."
    ),
)
