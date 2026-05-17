"""Session manager tests — verify background polling, buffering, and lifecycle."""

from __future__ import annotations

import asyncio

import pytest

from interactsh_mcp.session import SessionManager


@pytest.mark.asyncio
async def test_create_returns_payload_url(fake_server):
    mgr = SessionManager()
    try:
        session = await mgr.create(server=fake_server.host, poll_interval=0.05)
        info = session.info()
        assert info["server"] == fake_server.host
        assert info["payload_url"].endswith(f".{fake_server.host}")
        assert info["correlation_id"] in session.payload_url
        assert info["session_id"]
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_background_polling_buffers_events(fake_server, sample_interaction):
    mgr = SessionManager()
    try:
        session = await mgr.create(server=fake_server.host, poll_interval=0.05)
        fake_server.queue_interaction(session.client.correlation_id, sample_interaction)

        # drain() with wait>0 blocks until the background poller delivers.
        events = await session.drain(wait=2.0)
        assert len(events) == 1
        assert events[0].unique_id == sample_interaction["unique-id"]

        # Buffer is empty after a draining read.
        assert session.info()["buffered_count"] == 0
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_drain_no_clear_keeps_events(fake_server, sample_interaction):
    mgr = SessionManager()
    try:
        session = await mgr.create(server=fake_server.host, poll_interval=0.05)
        fake_server.queue_interaction(session.client.correlation_id, sample_interaction)
        await session.drain(wait=2.0)  # let background poll grab + buffer it
        # Re-queue so there's something in the buffer
        fake_server.queue_interaction(session.client.correlation_id, sample_interaction)
        # Wait for the poller to pick it up, then peek without clearing.
        await asyncio.sleep(0.2)
        peek = await session.drain(wait=1.0, clear=False)
        assert len(peek) == 1
        again = await session.drain(wait=0.0, clear=False)
        assert len(again) == 1
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_drain_with_wait_times_out(fake_server):
    mgr = SessionManager()
    try:
        session = await mgr.create(server=fake_server.host, poll_interval=0.05)
        # Nothing queued — drain with short wait returns []
        events = await session.drain(wait=0.2)
        assert events == []
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_list_and_destroy(fake_server):
    mgr = SessionManager()
    try:
        s1 = await mgr.create(server=fake_server.host, poll_interval=0.05)
        s2 = await mgr.create(server=fake_server.host, poll_interval=0.05)
        assert len(await mgr.list()) == 2

        await mgr.destroy(s1.id)
        remaining = {s.id for s in await mgr.list()}
        assert remaining == {s2.id}

        with pytest.raises(KeyError):
            await mgr.destroy(s1.id)
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_new_payload_shares_correlation_id(fake_server):
    mgr = SessionManager()
    try:
        session = await mgr.create(server=fake_server.host, poll_interval=0.05)
        extra = mgr.new_payload(session)
        assert extra != session.payload_url
        assert extra.startswith(session.client.correlation_id)
    finally:
        await mgr.aclose()


@pytest.mark.asyncio
async def test_poll_errors_are_captured_not_raised(fake_server, monkeypatch):
    """A transient poll failure should land in last_error, not crash the loop."""
    mgr = SessionManager()
    try:
        session = await mgr.create(server=fake_server.host, poll_interval=0.05)

        async def boom():
            raise RuntimeError("simulated network blip")

        # Patch the underlying client's poll to raise once.
        original = session.client.poll
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated network blip")
            return await original()

        session.client.poll = flaky  # type: ignore[method-assign]
        await asyncio.sleep(0.3)
        # Loop survived; last_error was set, then cleared on next successful poll.
        assert calls["n"] >= 2
    finally:
        await mgr.aclose()
