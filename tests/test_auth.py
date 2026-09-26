from __future__ import annotations

import asyncio
import base64
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from wavecast.auth import AuthTokenError, JwksJWTVerifier


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _key_set(private_key: Ed25519PrivateKey) -> dict[str, str]:
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64url(public_key), "kid": "test-key"}


def _token(private_key: Ed25519PrivateKey, **claims: object) -> str:
    payload = {
        "sub": "wavecast-user-123",
        "iss": "https://wavecast.example",
        "aud": "https://wavecast.example",
        "exp": int(time.time()) + 60,
        **claims,
    }
    return jwt.encode(payload, private_key, algorithm="EdDSA", headers={"kid": "test-key"})


def test_better_auth_jwt_resolves_stable_user_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    verifier = JwksJWTVerifier(
        "https://wavecast.example/api/auth/jwks",
        "https://wavecast.example",
        "https://wavecast.example",
    )

    async def get_key(key_id: str, *, refresh: bool = False) -> dict[str, str]:
        assert key_id == "test-key"
        del refresh
        return _key_set(private_key)

    monkeypatch.setattr(verifier, "_key", get_key)
    subject = asyncio.run(verifier.verify(_token(private_key)))

    assert subject == "wavecast-user-123"


def test_unknown_kid_forces_at_most_one_jwks_refresh_per_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = Ed25519PrivateKey.generate()
    verifier = JwksJWTVerifier(
        "https://wavecast.example/api/auth/jwks",
        "https://wavecast.example",
        "https://wavecast.example",
    )
    token = jwt.encode(
        {
            "sub": "wavecast-user-123",
            "iss": "https://wavecast.example",
            "aud": "https://wavecast.example",
            "exp": int(time.time()) + 60,
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "unknown-key"},
    )

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, list[dict[str, str]]]:
            return {"keys": [_key_set(private_key)]}

    class Client:
        requests = 0

        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, _: str) -> Response:
            Client.requests += 1
            return Response()

    monkeypatch.setattr("wavecast.auth.httpx.AsyncClient", Client)

    async def verify_twice() -> None:
        for _ in range(2):
            with pytest.raises(AuthTokenError, match="invalid_token"):
                await verifier.verify(token)

    asyncio.run(verify_twice())
    assert Client.requests == 1


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://attacker.example"},
        {"aud": "other-service"},
        {"exp": int(time.time()) - 60},
    ],
)
def test_better_auth_jwt_rejects_wrong_issuer_audience_or_expiry(
    monkeypatch: pytest.MonkeyPatch, claims: dict[str, object]
) -> None:
    private_key = Ed25519PrivateKey.generate()
    verifier = JwksJWTVerifier(
        "https://wavecast.example/api/auth/jwks",
        "https://wavecast.example",
        "https://wavecast.example",
    )

    async def get_key(key_id: str, *, refresh: bool = False) -> dict[str, str]:
        assert key_id == "test-key"
        del refresh
        return _key_set(private_key)

    monkeypatch.setattr(verifier, "_key", get_key)
    with pytest.raises(AuthTokenError, match="invalid_token"):
        asyncio.run(verifier.verify(_token(private_key, **claims)))
