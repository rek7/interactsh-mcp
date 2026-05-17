"""interactsh-mcp — MCP server for ProjectDiscovery's Interactsh OOB testing platform."""

from .client import InteractshClient, InteractshError, Interaction
from .session import Session, SessionManager

__version__ = "0.1.0"
__all__ = [
    "InteractshClient",
    "InteractshError",
    "Interaction",
    "Session",
    "SessionManager",
]
