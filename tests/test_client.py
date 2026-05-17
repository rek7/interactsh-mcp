"""Client unit tests — run RSA→AES round-trips against an in-process fake server."""

from __future__ import annotations

import pytest

from interactsh_mcp.client import (
    CORRELATION_ID_LENGTH,
    NONCE_LENGTH,
    InteractshClient,
    InteractshError,
)


@pytest.mark.asyncio
async def test_register_poll_empty_then_deregister(fake_server):
    client = InteractshClient(server=fake_server.host)
    await client.register()
    assert client.registered
    assert fake_server.register_calls == 1
    assert client.correlation_id in fake_server.sessions

    events = await client.poll()
    assert events == []
    assert fake_server.poll_calls == 1

    await client.aclose()
    assert fake_server.deregister_calls == 1
    assert client.correlation_id not in fake_server.sessions


@pytest.mark.asyncio
async def test_poll_decrypts_buffered_interaction(fake_server, sample_interaction):
    async with InteractshClient(server=fake_server.host) as client:
        fake_server.queue_interaction(client.correlation_id, sample_interaction)
        events = await client.poll()

    assert len(events) == 1
    ev = events[0]
    assert ev.protocol == "dns"
    assert ev.unique_id == sample_interaction["unique-id"]
    assert ev.raw_request == sample_interaction["raw-request"]
    assert ev.remote_address == "203.0.113.5:54321"
    # Original payload preserved in raw for protocol-specific consumers.
    assert ev.raw == sample_interaction


@pytest.mark.asyncio
async def test_poll_handles_multiple_events(fake_server, sample_interaction):
    async with InteractshClient(server=fake_server.host) as client:
        for i in range(5):
            ev = dict(sample_interaction, **{"unique-id": f"id-{i}"})
            fake_server.queue_interaction(client.correlation_id, ev)
        events = await client.poll()

    assert [e.unique_id for e in events] == [f"id-{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_token_is_sent_as_raw_authorization(fake_server_with_token):
    """Interactsh expects the raw token in Authorization (no Bearer prefix)."""
    async with InteractshClient(
        server=fake_server_with_token.host, token="s3cret-token"
    ) as client:
        assert client.registered
        await client.poll()


@pytest.mark.asyncio
async def test_missing_token_is_rejected(fake_server_with_token):
    client = InteractshClient(server=fake_server_with_token.host)
    with pytest.raises(InteractshError, match="HTTP 401"):
        await client.register()
    await client.aclose()


@pytest.mark.asyncio
async def test_wrong_token_is_rejected(fake_server_with_token):
    client = InteractshClient(server=fake_server_with_token.host, token="wrong")
    with pytest.raises(InteractshError, match="HTTP 401"):
        await client.register()
    await client.aclose()


def test_payload_hostname_structure():
    client = InteractshClient(server="example.test")
    payload = client.generate_payload()
    assert payload.endswith(".example.test")
    label = payload.split(".", 1)[0]
    assert len(label) == CORRELATION_ID_LENGTH + NONCE_LENGTH
    assert label.startswith(client.correlation_id)
    # Two payloads from the same client share the correlation-id, differ in nonce.
    p2 = client.generate_payload()
    assert p2 != payload
    assert p2.split(".", 1)[0].startswith(client.correlation_id)


def test_default_server_is_picked_from_rotation():
    from interactsh_mcp.client import DEFAULT_SERVERS

    client = InteractshClient()
    assert client.server in DEFAULT_SERVERS


@pytest.mark.asyncio
async def test_poll_before_register_raises():
    client = InteractshClient(server="example.test")
    with pytest.raises(InteractshError, match="must be registered"):
        await client.poll()
    await client.aclose()


@pytest.mark.asyncio
async def test_aclose_is_idempotent(fake_server):
    client = InteractshClient(server=fake_server.host)
    await client.register()
    await client.aclose()
    await client.aclose()  # second call is a no-op, not an error
    assert fake_server.deregister_calls == 1
