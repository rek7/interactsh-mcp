"""Optional live integration tests — exercise a real interactsh server.

Skipped by default. To run::

    INTERACTSH_LIVE=1 pytest tests/test_live.py

These hit the public ``oast.pro`` rotation (or your ``INTERACTSH_SERVER``).
"""

from __future__ import annotations

import asyncio
import os
import socket

import pytest

from interactsh_mcp.client import InteractshClient


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_register_and_dns_callback():
    server = os.environ.get("INTERACTSH_SERVER") or None
    token = os.environ.get("INTERACTSH_TOKEN") or None
    async with InteractshClient(server=server, token=token) as client:
        payload = client.generate_payload()
        # Trigger a DNS lookup against the payload so the server records an interaction.
        try:
            socket.gethostbyname(payload)
        except socket.gaierror:
            pass  # NXDOMAIN is fine — the lookup still reaches interactsh.

        # Give the server a few seconds to ingest the interaction.
        events: list = []
        for _ in range(10):
            events = await client.poll()
            if events:
                break
            await asyncio.sleep(1.0)

        assert events, "no DNS callback received from live interactsh server"
        assert any(e.protocol in {"dns", "DNS"} for e in events)
