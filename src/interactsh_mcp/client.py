"""Async Python implementation of the Interactsh client protocol.

Speaks directly to an Interactsh server (default ``oast.pro`` and siblings)
over HTTP. Performs RSA-2048 keygen, registers a session, polls for
interactions, and decrypts the AES-256-CTR payloads using an RSA-OAEP-wrapped
key. No external CLI dependency.

Reference implementation: https://github.com/projectdiscovery/interactsh
(``pkg/client/client.go``).
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import secrets
import string
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_SERVERS: tuple[str, ...] = (
    "oast.pro",
    "oast.live",
    "oast.site",
    "oast.online",
    "oast.fun",
    "oast.me",
)

CORRELATION_ID_LENGTH = 20
NONCE_LENGTH = 13
# The interactsh nonce uses an alphanumeric (lowercase) alphabet — matches the
# subset of zbase32 letters that are also valid DNS labels.
_NONCE_ALPHABET = string.ascii_lowercase + string.digits


class InteractshError(RuntimeError):
    """Raised when the Interactsh server returns an error or a response cannot be decrypted."""


@dataclass
class Interaction:
    """A single decrypted interaction event.

    The ``raw`` field always contains the full decoded JSON dict from the
    server — additional protocol-specific fields (DNS, HTTP, SMTP, …) are
    available there.
    """

    protocol: str
    unique_id: str
    full_id: str
    raw_request: str | None
    raw_response: str | None
    remote_address: str | None
    timestamp: str | None
    q_type: str | None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "Interaction":
        return cls(
            protocol=payload.get("protocol", ""),
            unique_id=payload.get("unique-id", ""),
            full_id=payload.get("full-id", ""),
            raw_request=payload.get("raw-request"),
            raw_response=payload.get("raw-response"),
            remote_address=payload.get("remote-address"),
            timestamp=payload.get("timestamp"),
            q_type=payload.get("q-type"),
            raw=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "unique_id": self.unique_id,
            "full_id": self.full_id,
            "raw_request": self.raw_request,
            "raw_response": self.raw_response,
            "remote_address": self.remote_address,
            "timestamp": self.timestamp,
            "q_type": self.q_type,
            "raw": self.raw,
        }


def _generate_correlation_id(length: int = CORRELATION_ID_LENGTH) -> str:
    """Produce a 20-char lowercase-alphanumeric ID matching interactsh's defaults."""
    return "".join(secrets.choice(_NONCE_ALPHABET) for _ in range(length))


def _generate_nonce(length: int = NONCE_LENGTH) -> str:
    return "".join(secrets.choice(_NONCE_ALPHABET) for _ in range(length))


def _pem_public_key_b64(private_key: rsa.RSAPrivateKey) -> str:
    """Encode the public key as base64-wrapped PEM (matches the Go client)."""
    pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(pem).decode("ascii")


def _decrypt_payload(
    private_key: rsa.RSAPrivateKey,
    aes_key_b64: str,
    data_items: list[str],
) -> list[dict[str, Any]]:
    """Match interactsh's wire format: RSA-OAEP-SHA256 → AES-256-CTR(IV‖CT)."""
    wrapped = base64.b64decode(aes_key_b64)
    aes_key = private_key.decrypt(
        wrapped,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    out: list[dict[str, Any]] = []
    for item in data_items:
        blob = base64.b64decode(item)
        if len(blob) < 16:
            raise InteractshError("ciphertext shorter than AES block size")
        iv, ciphertext = blob[:16], blob[16:]
        cipher = Cipher(algorithms.AES(aes_key), modes.CTR(iv))
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        try:
            out.append(json.loads(plaintext))
        except json.JSONDecodeError as exc:
            raise InteractshError(f"decrypted payload is not JSON: {exc}") from exc
    return out


class InteractshClient:
    """A single registered Interactsh session.

    The client is *not* started until :meth:`register` is awaited. Pair it
    with :class:`~interactsh_mcp.session.Session` for background polling, or
    drive it directly for one-shot use.

    Parameters
    ----------
    server:
        Hostname of the interactsh server (e.g. ``oast.pro``). If ``None``,
        one is picked at random from :data:`DEFAULT_SERVERS`.
    token:
        Optional bearer token. Sent as the raw ``Authorization`` header value
        (no ``Bearer`` prefix) to match the upstream Go client.
    correlation_id_length:
        Length of the correlation-id portion of generated hostnames. The
        upstream default of 20 is almost always correct; only change it if
        your self-hosted server uses ``-cidl``.
    nonce_length:
        Length of the random nonce appended to the correlation-id when
        producing payload hostnames. Default 13 (so 33 chars total).
    scheme:
        ``https`` (default) or ``http`` — only change for local self-hosted
        testing.
    """

    def __init__(
        self,
        server: str | None = None,
        token: str | None = None,
        *,
        correlation_id_length: int = CORRELATION_ID_LENGTH,
        nonce_length: int = NONCE_LENGTH,
        scheme: str = "https",
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.server = server or random.choice(DEFAULT_SERVERS)
        self.token = token
        self.scheme = scheme
        self.correlation_id_length = correlation_id_length
        self.nonce_length = nonce_length

        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.correlation_id = _generate_correlation_id(correlation_id_length)
        self.secret_key = str(uuid.uuid4())

        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._registered = False
        self._closed = False

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.server}"

    @property
    def registered(self) -> bool:
        return self._registered

    def generate_payload(self) -> str:
        """Return a fresh interaction hostname: ``<cid><nonce>.<server>``."""
        nonce = _generate_nonce(self.nonce_length)
        return f"{self.correlation_id}{nonce}.{self.server}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    async def register(self) -> None:
        if self._registered:
            return
        body = {
            "public-key": _pem_public_key_b64(self._private_key),
            "secret-key": self.secret_key,
            "correlation-id": self.correlation_id,
        }
        resp = await self._http.post(
            f"{self.base_url}/register",
            headers=self._headers(),
            json=body,
        )
        if resp.status_code != 200:
            raise InteractshError(
                f"register failed: HTTP {resp.status_code}: {resp.text.strip()}"
            )
        self._registered = True

    async def poll(self) -> list[Interaction]:
        """Fetch and decrypt any pending interactions.

        Returns an empty list when nothing is waiting. The server clears its
        buffer for this correlation-id on each successful poll.
        """
        if not self._registered:
            raise InteractshError("client must be registered before polling")
        resp = await self._http.get(
            f"{self.base_url}/poll",
            headers=self._headers(),
            params={"id": self.correlation_id, "secret": self.secret_key},
        )
        if resp.status_code != 200:
            raise InteractshError(
                f"poll failed: HTTP {resp.status_code}: {resp.text.strip()}"
            )
        payload = resp.json()
        data: list[str] = payload.get("data") or []
        if not data:
            return []
        aes_key = payload.get("aes_key")
        if not aes_key:
            raise InteractshError("poll response had data but no aes_key")
        decrypted = _decrypt_payload(self._private_key, aes_key, data)
        return [Interaction.from_json(item) for item in decrypted]

    async def deregister(self) -> None:
        """Tell the server to forget this correlation-id. Idempotent."""
        if not self._registered:
            return
        body = {
            "correlation-id": self.correlation_id,
            "secret-key": self.secret_key,
        }
        try:
            await self._http.post(
                f"{self.base_url}/deregister",
                headers=self._headers(),
                json=body,
            )
        finally:
            self._registered = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.deregister()
        except Exception:
            # Best-effort: never raise from aclose, callers expect cleanup to succeed.
            pass
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> "InteractshClient":
        await self.register()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()
