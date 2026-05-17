"""Targeting a self-hosted Interactsh server with token authentication.

Self-hosted servers started with ``-auth`` print a random token at boot;
pass it as ``INTERACTSH_TOKEN`` or as the ``token=`` kwarg. Without
``-auth``, omit the token entirely.

Run::

    INTERACTSH_SERVER=interact.example.com \\
    INTERACTSH_TOKEN=your-server-token \\
    python examples/03_self_hosted_with_token.py
"""

from __future__ import annotations

import asyncio
import os
import socket

from interactsh_mcp import InteractshClient


async def main() -> None:
    server = os.environ.get("INTERACTSH_SERVER")
    token = os.environ.get("INTERACTSH_TOKEN")
    if not server:
        raise SystemExit("set INTERACTSH_SERVER (and INTERACTSH_TOKEN if needed)")

    async with InteractshClient(server=server, token=token) as client:
        payload_url = client.generate_payload()
        print(f"payload URL: {payload_url}")

        try:
            socket.gethostbyname(payload_url)
        except socket.gaierror:
            pass

        for _ in range(15):
            events = await client.poll()
            if events:
                print(f"received {len(events)} event(s):")
                for ev in events:
                    print(f"  {ev.protocol} from {ev.remote_address}")
                break
            await asyncio.sleep(1)
        else:
            print("no callback received within timeout")


if __name__ == "__main__":
    asyncio.run(main())
