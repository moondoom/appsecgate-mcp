from __future__ import annotations

from appsecgate_mcp.agent.master import MasterClient


def test_master_client_uses_mcp_endpoint_without_redirect():
    client = MasterClient("http://master.test/", "key")
    assert client.url == "http://master.test/mcp/"
