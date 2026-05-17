"""Sync-style usage by wrapping the async API.

The library is async-first, but if you're calling from synchronous code
(e.g. a CTF script, Jupyter notebook without IPython's await magic), just
wrap calls in ``asyncio.run``.

Run::

    python examples/04_sync_wrapper.py
"""

from __future__ import annotations

import asyncio
import socket
import time

from interactsh_mcp import InteractshClient


def poll_until(server: str | None = None, token: str | None = None, *, timeout: float = 30) -> list:
    """Blocking helper: register, mint a payload, wait for the first callback."""

    async def _run():
        async with InteractshClient(server=server, token=token) as client:
            payload = client.generate_payload()
            print(f"payload URL: {payload}")

            try:
                socket.gethostbyname(payload)
            except socket.gaierror:
                pass

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                events = await client.poll()
                if events:
                    return events
                await asyncio.sleep(1)
            return []

    return asyncio.run(_run())


if __name__ == "__main__":
    for ev in poll_until():
        print(f"  {ev.protocol:5} from {ev.remote_address}")
