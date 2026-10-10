"""Нормализация: fingerprint, дедупликация, severity-маппинг."""

from appsecgate_mcp.normalization.dedup import Deduplicator
from appsecgate_mcp.normalization.fingerprint import FingerprintGenerator
from appsecgate_mcp.normalization.normalizer import Normalizer

__all__ = ["Deduplicator", "FingerprintGenerator", "Normalizer"]
