"""Storage layer: SQLite-базы shown_findings, feedback, scan_cache."""

from appsecgate_mcp.storage.db import Database, init_databases
from appsecgate_mcp.storage.logical_id import compute_logical_id, extract_scope_key
from appsecgate_mcp.storage.stores import (
    FeedbackStore,
    FindingContextStore,
    FindingIdentityStore,
    ProjectsStore,
    ScanCacheStore,
    ShownFindingsStore,
    SuppressionStore,
)

__all__ = [
    "Database",
    "FeedbackStore",
    "FindingContextStore",
    "FindingIdentityStore",
    "ProjectsStore",
    "ScanCacheStore",
    "ShownFindingsStore",
    "SuppressionStore",
    "compute_logical_id",
    "extract_scope_key",
    "init_databases",
]
