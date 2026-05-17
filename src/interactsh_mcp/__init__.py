"""interactsh-mcp — Python bindings + MCP server for ProjectDiscovery's Interactsh.

Two ways to use this package:

1. **As an MCP server** — install and run ``interactsh-mcp``; the agent gets
   the tools documented in the README.

2. **As an async Python library** — import directly and drive Interactsh
   from your own code::

       import asyncio
       from interactsh_mcp import InteractshClient

       async def main():
           async with InteractshClient() as client:
               print(client.generate_payload())
               # ... use the payload, then:
               for event in await client.poll():
                   print(event.protocol, event.remote_address)

       asyncio.run(main())

   For long-running multi-payload setups, use :class:`SessionManager` —
   it polls in the background and buffers events for you.
"""

from .client import (
    DEFAULT_SERVERS,
    InteractshClient,
    InteractshError,
    Interaction,
)
from .session import Session, SessionManager

__version__ = "0.1.1"
__all__ = [
    "DEFAULT_SERVERS",
    "InteractshClient",
    "InteractshError",
    "Interaction",
    "Session",
    "SessionManager",
    "__version__",
]
