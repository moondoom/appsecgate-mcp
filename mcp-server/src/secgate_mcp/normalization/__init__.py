"""Нормализация: fingerprint, дедупликация, severity-маппинг."""

from secgate_mcp.normalization.dedup import Deduplicator
from secgate_mcp.normalization.fingerprint import FingerprintGenerator
from secgate_mcp.normalization.normalizer import Normalizer

__all__ = ["Deduplicator", "FingerprintGenerator", "Normalizer"]
