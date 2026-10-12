"""Нормализация: fingerprint, дедупликация, severity-маппинг."""

from appsecgate_mcp.normalization.dedup import Deduplicator
from appsecgate_mcp.normalization.fingerprint import FingerprintGenerator
from appsecgate_mcp.normalization.normalizer import Normalizer
from appsecgate_mcp.normalization.redactor import Redactor
from appsecgate_mcp.normalization.suppress_filter import ConfigSuppressFilter

__all__ = [
    "ConfigSuppressFilter",
    "Deduplicator",
    "FingerprintGenerator",
    "Normalizer",
    "Redactor",
]
