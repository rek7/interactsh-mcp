"""One-shot Interactsh usage: register, mint a payload, poll, deregister.

Run::

    pip install interactsh-mcp
    python examples/01_one_shot.py

This is the lowest-overhead pattern for an SSRF/OOB check in a script: open
a context-managed client, hand the payload URL to your test target, then
poll for the callback. The client deregisters on exit.
"""

from __future__ import annotations

import asyncio
import socket

from interactsh_mcp import InteractshClient


async def main() -> None:
    # Pass server=... and/or token=... to target a self-hosted instance.
    # With no args, a random oast.* server from the public rotation is used.
    async with InteractshClient() as client:
        payload_url = client.generate_payload()
        print(f"payload URL: {payload_url}")
        print(f"server:      {client.server}")

        # In a real test you'd embed the URL in your exploit and trigger the
        # target. Here we just resolve it via DNS so interactsh records it.
        try:
            socket.gethostbyname(payload_url)
        except socket.gaierror:
            pass

        # Poll up to 10s for the callback.
        for _ in range(10):
            events = await client.poll()
            if events:
                for ev in events:
                    print(f"  {ev.protocol:5} {ev.q_type or '':5} from {ev.remote_address}")
                break
            await asyncio.sleep(1)
        else:
            print("no callback received")


if __name__ == "__main__":
    asyncio.run(main())
