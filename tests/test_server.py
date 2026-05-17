"""MCP server tool tests — drive the tools directly without an MCP transport."""

from __future__ import annotations

import pytest

from interactsh_mcp.server import build_server
from interactsh_mcp.session import SessionManager


async def _call(mcp, name, **kwargs):
    """Invoke a registered FastMCP tool by name and return its result payload."""
    result = await mcp.call_tool(name, kwargs)
    # FastMCP returns (content_list, structured_payload) in recent versions;
    # older versions return just the content list. Handle both.
    if isinstance(result, tuple) and len(result) == 2:
        return result[1]
    return result


@pytest.mark.asyncio
async def test_create_and_destroy_session(fake_server):
    mgr = SessionManager(default_server=fake_server.host)
    mcp = build_server(manager=mgr)
    try:
        created = await _call(mcp, "create_session", poll_interval=0.05)
        # Result may be wrapped in a {"result": ...} shell by FastMCP — unwrap.
        info = created.get("result", created) if isinstance(created, dict) else created
        sid = info["session_id"]
        assert info["payload_url"].endswith(f".{fake_server.host}")

        listed = await _call(mcp, "list_sessions")
        listed = listed.get("result", listed) if isinstance(listed, dict) else listed
        assert any(s["session_id"] == sid for s in listed)

        destroyed = await _call(mcp, "destroy_session", session_id=sid)
        destroyed = destroyed.get("result", destroyed) if isinstance(destroyed, dict) else destroyed
        assert destroyed["destroyed"] is True
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_poll_interactions_returns_decrypted_events(fake_server, sample_interaction):
    mgr = SessionManager(default_server=fake_server.host)
    mcp = build_server(manager=mgr)
    try:
        created = await _call(mcp, "create_session", poll_interval=0.05)
        info = created.get("result", created) if isinstance(created, dict) else created
        sid = info["session_id"]

        session = await mgr.get(sid)
        fake_server.queue_interaction(session.client.correlation_id, sample_interaction)

        polled = await _call(mcp, "poll_interactions", session_id=sid, wait=2.0)
        polled = polled.get("result", polled) if isinstance(polled, dict) else polled
        assert polled["count"] == 1
        assert polled["interactions"][0]["protocol"] == "dns"
        assert polled["interactions"][0]["unique_id"] == sample_interaction["unique-id"]
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_get_default_servers():
    mcp = build_server(manager=SessionManager())
    servers = await _call(mcp, "get_default_servers")
    servers = servers.get("result", servers) if isinstance(servers, dict) else servers
    assert "oast.pro" in servers
    assert "oast.live" in servers
