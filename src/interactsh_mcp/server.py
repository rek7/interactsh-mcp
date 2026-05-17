"""FastMCP server exposing Interactsh sessions to LLMs.

Tools (all async):

- ``create_session``       — register a new interactsh session and return a payload URL.
- ``list_sessions``        — enumerate active sessions and their buffer counts.
- ``poll_interactions``    — drain buffered interactions; optionally block briefly for the first.
- ``new_payload``          — vend an additional payload URL on an existing session.
- ``destroy_session``      — deregister and clean up.
- ``get_default_servers``  — list the public oast.* hosts the default rotation uses.

Environment variables (used as fallbacks when a tool call omits them):

- ``INTERACTSH_SERVER`` — default self-hosted server hostname.
- ``INTERACTSH_TOKEN``  — default Authorization token.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import DEFAULT_SERVERS
from .session import SessionManager

log = logging.getLogger(__name__)


def build_server(manager: SessionManager | None = None) -> FastMCP:
    """Build (but don't run) the FastMCP server. Exposed for testing."""
    manager = manager or SessionManager(
        default_server=os.environ.get("INTERACTSH_SERVER") or None,
        default_token=os.environ.get("INTERACTSH_TOKEN") or None,
    )

    mcp = FastMCP(
        "interactsh",
        instructions=(
            "Tools for validating out-of-band (OOB) vulnerabilities via "
            "ProjectDiscovery's Interactsh. Call create_session to obtain a "
            "payload hostname, embed it in your test (DNS exfil, SSRF, "
            "log4shell, blind XSS callback, etc.), then call "
            "poll_interactions to confirm whether the target reached out."
        ),
    )

    @mcp.tool()
    async def create_session(
        server: str | None = None,
        token: str | None = None,
        poll_interval: float = 5.0,
        scheme: str = "https",
        correlation_id_length: int = 20,
    ) -> dict[str, Any]:
        """Register a new Interactsh session and return a payload URL.

        Args:
            server: Hostname of the interactsh server. Omit to use the
                ``INTERACTSH_SERVER`` env var, or — failing that — a random
                pick from the public ``oast.*`` rotation.
            token: Authorization token for self-hosted servers started with
                ``-auth``. Sent as the raw ``Authorization`` header.
            poll_interval: Seconds between background polls (default 5).
            scheme: ``https`` (default) or ``http`` for local testing.
            correlation_id_length: Override only if the upstream server uses
                a non-default ``-cidl``.

        Returns:
            A dict with ``session_id`` (use for later tool calls),
            ``payload_url`` (embed this in your OOB test), ``server``, and
            ``correlation_id``.
        """
        session = await manager.create(
            server=server,
            token=token,
            poll_interval=poll_interval,
            scheme=scheme,
            correlation_id_length=correlation_id_length,
        )
        return session.info()

    @mcp.tool()
    async def list_sessions() -> list[dict[str, Any]]:
        """List all active interactsh sessions."""
        sessions = await manager.list()
        return [s.info() for s in sessions]

    @mcp.tool()
    async def poll_interactions(
        session_id: str,
        wait: float = 0.0,
        clear: bool = True,
    ) -> dict[str, Any]:
        """Drain buffered interactions for a session.

        Args:
            session_id: ID returned by ``create_session``.
            wait: If > 0 and the buffer is empty, block up to this many
                seconds for the first event before returning. Useful when
                the caller wants to confirm a callback synchronously.
            clear: If True (default), empty the buffer after returning.
                Set to False to peek without consuming.

        Returns:
            A dict with ``count`` and ``interactions`` (each: protocol,
            unique_id, full_id, raw_request, raw_response, remote_address,
            timestamp, q_type, raw).
        """
        session = await manager.get(session_id)
        events = await session.drain(wait=wait, clear=clear)
        return {
            "session_id": session_id,
            "count": len(events),
            "interactions": [e.to_dict() for e in events],
        }

    @mcp.tool()
    async def new_payload(session_id: str) -> dict[str, Any]:
        """Generate an additional payload URL on an existing session.

        Useful when you want distinct callback URLs per test (each one ends
        up routed to the same session because the correlation-id is shared
        — only the nonce differs).
        """
        session = await manager.get(session_id)
        payload = manager.new_payload(session)
        return {"session_id": session_id, "payload_url": payload}

    @mcp.tool()
    async def destroy_session(session_id: str) -> dict[str, Any]:
        """Deregister and clean up a session."""
        await manager.destroy(session_id)
        return {"session_id": session_id, "destroyed": True}

    @mcp.tool()
    async def get_default_servers() -> list[str]:
        """List the public Interactsh hosts used by the default rotation."""
        return list(DEFAULT_SERVERS)

    mcp._interactsh_manager = manager  # type: ignore[attr-defined]  # for tests
    return mcp


def main() -> None:
    """Console-script entrypoint — runs the MCP server over stdio."""
    logging.basicConfig(
        level=os.environ.get("INTERACTSH_LOG_LEVEL", "WARNING").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    build_server().run()


if __name__ == "__main__":
    main()
