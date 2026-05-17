"""Multi-payload usage with SessionManager + background polling.

When you're running several tests in the same script (or a long-lived
process), SessionManager runs a background poller per session and buffers
events for you. ``drain(wait=...)`` blocks for the next event without
busy-looping.

Run::

    python examples/02_session_manager.py
"""

from __future__ import annotations

import asyncio
import socket

from interactsh_mcp import SessionManager


async def main() -> None:
    mgr = SessionManager()
    try:
        # One session can vend many distinct payload URLs (different nonces,
        # same correlation-id — all routed back to this session).
        session = await mgr.create(poll_interval=2.0)
        print(f"session_id:  {session.id}")
        print(f"server:      {session.client.server}")

        for i in range(3):
            payload = mgr.new_payload(session)
            print(f"\npayload #{i + 1}: {payload}")
            try:
                socket.gethostbyname(payload)
            except socket.gaierror:
                pass

            # Block up to 15s for the next callback. The background poller
            # delivers events into the buffer; drain returns whatever it has.
            events = await session.drain(wait=15)
            print(f"  received {len(events)} event(s)")
            for ev in events:
                print(f"    {ev.protocol:5} from {ev.remote_address}")

    finally:
        await mgr.aclose()


if __name__ == "__main__":
    asyncio.run(main())
