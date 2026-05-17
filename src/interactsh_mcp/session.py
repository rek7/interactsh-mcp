"""Session manager — wraps :class:`InteractshClient` with background polling.

The MCP server holds a single :class:`SessionManager`; each LLM-created
session corresponds to one :class:`Session`, which runs an asyncio task that
polls interactsh on a fixed interval and buffers any decrypted events for
later retrieval.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .client import DEFAULT_SERVERS, Interaction, InteractshClient, InteractshError

log = logging.getLogger(__name__)


@dataclass
class Session:
    id: str
    client: InteractshClient
    payload_url: str
    poll_interval: float
    created_at: float
    buffer: list[Interaction] = field(default_factory=list)
    _task: asyncio.Task[None] | None = None
    _new_event: asyncio.Event = field(default_factory=asyncio.Event)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_error: str | None = None

    def info(self) -> dict[str, Any]:
        return {
            "session_id": self.id,
            "payload_url": self.payload_url,
            "server": self.client.server,
            "correlation_id": self.client.correlation_id,
            "created_at": self.created_at,
            "buffered_count": len(self.buffer),
            "poll_interval": self.poll_interval,
            "last_error": self._last_error,
        }

    async def _poll_loop(self) -> None:
        try:
            while True:
                try:
                    events = await self.client.poll()
                    if events:
                        async with self._lock:
                            self.buffer.extend(events)
                        self._new_event.set()
                    self._last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — surface any poll failure
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    log.warning("session %s poll error: %s", self.id, exc)
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop(), name=f"interactsh-poll-{self.id}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def drain(
        self, *, wait: float = 0.0, clear: bool = True
    ) -> list[Interaction]:
        """Return buffered events. If ``wait`` > 0 and the buffer is empty,
        block up to that many seconds for the next event before returning.
        """
        async with self._lock:
            if self.buffer or wait <= 0:
                events = list(self.buffer)
                if clear:
                    self.buffer.clear()
                    self._new_event.clear()
                return events
            # Buffer empty — release the lock and wait outside it.
            self._new_event.clear()

        try:
            await asyncio.wait_for(self._new_event.wait(), timeout=wait)
        except asyncio.TimeoutError:
            return []

        async with self._lock:
            events = list(self.buffer)
            if clear:
                self.buffer.clear()
                self._new_event.clear()
            return events


class SessionManager:
    def __init__(self, default_server: str | None = None, default_token: str | None = None) -> None:
        self.default_server = default_server
        self.default_token = default_token
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    @property
    def default_servers(self) -> tuple[str, ...]:
        return DEFAULT_SERVERS

    async def create(
        self,
        *,
        server: str | None = None,
        token: str | None = None,
        poll_interval: float = 5.0,
        scheme: str = "https",
        correlation_id_length: int = 20,
    ) -> Session:
        client = InteractshClient(
            server=server or self.default_server,
            token=token if token is not None else self.default_token,
            scheme=scheme,
            correlation_id_length=correlation_id_length,
        )
        try:
            await client.register()
        except Exception:
            await client.aclose()
            raise

        session = Session(
            id=str(uuid.uuid4()),
            client=client,
            payload_url=client.generate_payload(),
            poll_interval=poll_interval,
            created_at=time.time(),
        )
        session.start()
        async with self._lock:
            self._sessions[session.id] = session
        return session

    async def get(self, session_id: str) -> Session:
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"unknown session_id: {session_id}")
        return session

    async def list(self) -> list[Session]:
        async with self._lock:
            return list(self._sessions.values())

    async def destroy(self, session_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            raise KeyError(f"unknown session_id: {session_id}")
        await session.stop()
        await session.client.aclose()

    async def aclose(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await session.stop()
            await session.client.aclose()

    def new_payload(self, session: Session) -> str:
        """Generate an additional fresh payload hostname for an existing session.

        Different nonces under the same correlation-id all route back to the
        same registered key, so a single session can vend many distinct URLs.
        """
        return session.client.generate_payload()
