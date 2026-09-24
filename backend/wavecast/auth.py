"""Optional authenticated identity boundary for guest-first API requests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import jwt


class AuthTokenError(ValueError):
    """A bearer token is present but cannot be trusted."""


@dataclass(frozen=True)
class AuthPrincipal:
    listener_id: str
    user_id: str | None = None


class JwksJWTVerifier:
    """Verify Better Auth JWT-plugin tokens against a bounded cached JWKS."""

    def __init__(self, jwks_url: str, issuer: str, audience: str) -> None:
        self.jwks_url = jwks_url
        self.issuer = issuer
        self.audience = audience
        self._keys: dict[str, dict[str, Any]] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def verify(self, token: str) -> str:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise AuthTokenError("invalid_token") from error
        key_id = header.get("kid")
        algorithm = header.get("alg")
        if not isinstance(key_id, str) or algorithm not in {"EdDSA", "ES256", "RS256"}:
            raise AuthTokenError("invalid_token")

        key_data = await self._key(key_id)
        if key_data is None:
            key_data = await self._key(key_id, refresh=True)
        if key_data is None:
            raise AuthTokenError("invalid_token")
        try:
            key = jwt.PyJWK.from_dict(key_data, algorithm=algorithm).key
            payload = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except (jwt.PyJWTError, ValueError, TypeError) as error:
            raise AuthTokenError("invalid_token") from error
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthTokenError("invalid_token")
        return subject

    async def _key(self, key_id: str, *, refresh: bool = False) -> dict[str, Any] | None:
        async with self._lock:
            if refresh or self._expires_at <= asyncio.get_running_loop().time():
                try:
                    async with httpx.AsyncClient(timeout=3.0, follow_redirects=False) as client:
                        response = await client.get(self.jwks_url)
                        response.raise_for_status()
                        body = response.json()
                except (httpx.HTTPError, ValueError) as error:
                    raise AuthTokenError("jwks_unavailable") from error
                if not isinstance(body, dict) or not isinstance(body.get("keys"), list):
                    raise AuthTokenError("invalid_jwks")
                self._keys = {
                    key["kid"]: key
                    for key in body["keys"]
                    if isinstance(key, dict) and isinstance(key.get("kid"), str)
                }
                self._expires_at = asyncio.get_running_loop().time() + 300
            return self._keys.get(key_id)
