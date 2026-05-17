"""Shared test helpers — a tiny in-process Interactsh server that mirrors the
real one's wire protocol just well enough to exercise the client end-to-end.

We do real RSA-OAEP wrapping and real AES-256-CTR encryption so the client's
decrypt path runs against genuine ciphertext.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass, field
from typing import Any

import pytest
import respx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from httpx import Response


@dataclass
class FakeServer:
    """Tracks registrations and lets tests inject pending interactions."""

    host: str = "interactsh.test"
    required_token: str | None = None
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    register_calls: int = 0
    poll_calls: int = 0
    deregister_calls: int = 0

    def _auth_ok(self, request) -> bool:
        if self.required_token is None:
            return True
        return request.headers.get("authorization") == self.required_token

    def queue_interaction(self, correlation_id: str, payload: dict[str, Any]) -> None:
        self.pending.setdefault(correlation_id, []).append(payload)

    def _on_register(self, request) -> Response:
        self.register_calls += 1
        if not self._auth_ok(request):
            return Response(401, json={"error": "unauthorized"})
        body = json.loads(request.content)
        pub_pem = base64.b64decode(body["public-key"])
        self.sessions[body["correlation-id"]] = {
            "secret-key": body["secret-key"],
            "public-key": pub_pem,
        }
        return Response(200, json={"message": "registration successful"})

    def _on_poll(self, request) -> Response:
        self.poll_calls += 1
        if not self._auth_ok(request):
            return Response(401, json={"error": "unauthorized"})
        cid = request.url.params.get("id")
        secret = request.url.params.get("secret")
        session = self.sessions.get(cid)
        if not session or session["secret-key"] != secret:
            return Response(401, json={"error": "unknown session"})

        events = self.pending.pop(cid, [])
        if not events:
            return Response(200, json={"data": [], "extra": [], "aes_key": ""})

        # Generate a fresh AES-256 key, wrap with RSA-OAEP-SHA256, encrypt each
        # event in CTR mode with a per-event 16-byte IV prepended.
        public_key = serialization.load_pem_public_key(session["public-key"])
        aes_key = secrets.token_bytes(32)
        wrapped = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

        encrypted = []
        for ev in events:
            iv = secrets.token_bytes(16)
            cipher = Cipher(algorithms.AES(aes_key), modes.CTR(iv))
            enc = cipher.encryptor()
            ct = enc.update(json.dumps(ev).encode()) + enc.finalize()
            encrypted.append(base64.b64encode(iv + ct).decode())

        return Response(
            200,
            json={
                "data": encrypted,
                "extra": [],
                "aes_key": base64.b64encode(wrapped).decode(),
            },
        )

    def _on_deregister(self, request) -> Response:
        self.deregister_calls += 1
        if not self._auth_ok(request):
            return Response(401, json={"error": "unauthorized"})
        body = json.loads(request.content)
        self.sessions.pop(body.get("correlation-id", ""), None)
        return Response(200, json={"message": "deregistration successful"})


@pytest.fixture
def fake_server():
    server = FakeServer()
    with respx.mock(base_url=f"https://{server.host}", assert_all_called=False) as router:
        router.post("/register").mock(side_effect=server._on_register)
        router.get("/poll").mock(side_effect=server._on_poll)
        router.post("/deregister").mock(side_effect=server._on_deregister)
        yield server


@pytest.fixture
def fake_server_with_token():
    server = FakeServer(required_token="s3cret-token")
    with respx.mock(base_url=f"https://{server.host}", assert_all_called=False) as router:
        router.post("/register").mock(side_effect=server._on_register)
        router.get("/poll").mock(side_effect=server._on_poll)
        router.post("/deregister").mock(side_effect=server._on_deregister)
        yield server


@pytest.fixture
def sample_interaction() -> dict[str, Any]:
    return {
        "protocol": "dns",
        "unique-id": "c7lci09s8mts0o3og0g0abc123def",
        "full-id": "c7lci09s8mts0o3og0g0abc123def.interactsh.test",
        "q-type": "A",
        "raw-request": ";; opcode: QUERY, status: NOERROR, id: 42\n",
        "raw-response": ";; opcode: QUERY, status: NOERROR, id: 42\n",
        "remote-address": "203.0.113.5:54321",
        "timestamp": "2026-05-17T12:00:00Z",
    }


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.live tests unless INTERACTSH_LIVE=1."""
    if os.environ.get("INTERACTSH_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="set INTERACTSH_LIVE=1 to run live tests")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
