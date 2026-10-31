"""HTTP API master-сервера (MS-4)."""

from __future__ import annotations

from appsecgate_master.api.app import create_app
from appsecgate_master.api.config import MasterSettings

__all__ = ["MasterSettings", "create_app"]
