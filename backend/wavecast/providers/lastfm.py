"""Last.fm community tags as an optional, degradable source of artist names.

Last.fm only suggests *who to look for*; the catalog still decides what is playable and the
Curator still decides the route.  A missing key, a timeout, a rate limit or a malformed reply
all return an empty list, so discovery is never slower or less reliable than without it.

The API key travels in the query string (Last.fm offers nothing else), so it is never logged:
failures are reported by exception class only.
"""

from __future__ import annotations

import logging
from time import monotonic

import httpx

from .config import ProviderSettings

logger = logging.getLogger(__name__)

ENDPOINT = "https://ws.audioscrobbler.com/2.0/"
_TTL_SECONDS = 24 * 60 * 60
_TIMEOUT_SECONDS = 4.0
_MAX_CACHE_ENTRIES = 64


class LastFmArtistHints:
    """``ArtistHintProvider`` backed by ``tag.gettopartists``, cached per tag for a day."""

    def __init__(
        self,
        api_key: str | None,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = _TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._timeout = timeout_seconds
        self._cache: dict[tuple[str, int], tuple[float, list[str]]] = {}

    @classmethod
    def from_settings(cls, settings: ProviderSettings) -> LastFmArtistHints | None:
        """None when no key is configured, so callers can skip the dependency entirely."""

        return cls(settings.lastfm_api_key) if settings.lastfm_api_key else None

    async def artists_for_tag(self, tag: str, *, limit: int) -> list[str]:
        tag = tag.strip().lower()
        if not self._api_key or not tag or limit < 1:
            return []
        cache_key = (tag, limit)
        cached = self._cache.get(cache_key)
        if cached is not None and monotonic() - cached[0] < _TTL_SECONDS:
            return list(cached[1])
        try:
            names = await self._fetch(tag, limit)
        except Exception as error:  # noqa: BLE001 - an optional signal must never break discovery
            logger.warning("lastfm_failed tag=%s error_type=%s", tag, type(error).__name__)
            return []
        if len(self._cache) >= _MAX_CACHE_ENTRIES:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = (monotonic(), names)
        return list(names)

    async def _fetch(self, tag: str, limit: int) -> list[str]:
        params = {
            "method": "tag.gettopartists",
            "tag": tag,
            "limit": str(limit),
            "api_key": self._api_key or "",
            "format": "json",
        }
        if self._client is not None:
            response = await self._client.get(ENDPOINT, params=params, timeout=self._timeout)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(ENDPOINT, params=params)
        response.raise_for_status()
        payload = response.json()
        # Last.fm reports errors (bad key, rate limit) as HTTP 200 with an "error" field.
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("lastfm_error_payload")
        artists = payload.get("topartists", {}).get("artist", [])
        if not isinstance(artists, list):
            return []
        names: list[str] = []
        for item in artists:
            name = item.get("name") if isinstance(item, dict) else None
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        return names[:limit]
