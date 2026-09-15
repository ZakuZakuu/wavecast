"""Audius read-only music catalog adapter.

The adapter deliberately exposes only the provider-neutral ``MusicProvider`` contract.
Audius identifiers and response fields are normalized before they reach composition or
episode runtime code.  Read-only API access works without credentials; an optional key
can be supplied later for higher rate limits.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .config import ProviderSettings
from .contracts import AudioAsset, AudioAssetType, TrackMetadata
from .errors import ProviderInvalidResponseError
from .http import request_json


class AudiusMusicProvider:
    """Low-cost read-only Audius catalog and stream resolver."""

    provider_name = "audius"
    default_base_url = "https://api.audius.co/v1"

    def __init__(
        self,
        settings: ProviderSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        settings = settings or ProviderSettings()
        self.settings = settings
        self.base_url = (base_url or settings.audius_base_url or self.default_base_url).rstrip("/")
        self.api_key = api_key or settings.audius_api_key
        self.client = client or httpx.AsyncClient(timeout=settings.timeout_seconds)
        self._owns_client = client is None

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        payload = await self._request("/tracks/search", params={"query": query, "limit": limit})
        items = payload.get("data")
        if not isinstance(items, list):
            return []
        return [
            normalized
            for item in items
            if isinstance(item, dict)
            for normalized in [self._normalize_track(item)]
        ]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        audius_id = _provider_id(track_ref)
        payload = await self._request(f"/tracks/{quote(audius_id, safe='')}")
        item = payload.get("data")
        if isinstance(item, list):
            item = item[0] if item else None
        if not isinstance(item, dict):
            raise ProviderInvalidResponseError("audius returned no track metadata")
        return self._normalize_track(item)

    async def resolve_track_proposal(self, proposal: object) -> object | None:
        """Resolve an artist/title proposal only against canonical catalog metadata."""
        artist = _normalized_name(getattr(proposal, "artist", ""))
        title = _normalized_name(getattr(proposal, "title", ""))
        if not artist or not title:
            return None
        for metadata in await self.search(f"{artist} {title}", limit=5):
            if _normalized_name(metadata.artist) == artist and _normalized_name(metadata.title) == title:
                from wavecast.intelligence.models import ResolvedTrack

                return ResolvedTrack(
                    track_ref=metadata.track_ref,
                    canonical_artist=metadata.artist,
                    canonical_title=metadata.title,
                )
        return None

    async def resolve_proposal(self, proposal: object) -> object | None:
        return await self.resolve_track_proposal(proposal)

    async def get_playback_asset(self, track: object) -> AudioAsset:
        track_ref = getattr(track, "track_ref", None)
        if not isinstance(track_ref, str) or not track_ref:
            raise ProviderInvalidResponseError("audius playback requires a resolved track")
        metadata = await self.resolve_track(track_ref)
        if not metadata.playable:
            raise ProviderInvalidResponseError("audius track has no playable duration")
        audius_id = _provider_id(metadata.track_ref)
        return AudioAsset(
            asset_id=metadata.track_ref,
            asset_type=AudioAssetType.MUSIC,
            provider=self.provider_name,
            playback_url=f"{self.base_url}/tracks/{quote(audius_id, safe='')}/stream",
            duration=metadata.duration_seconds,
            metadata=metadata.metadata,
        )

    async def playback_asset(self, track: object) -> AudioAsset:
        return await self.get_playback_asset(track)

    async def get_stream_source(self, track_ref: str) -> str:
        from wavecast.intelligence.models import ResolvedTrack

        return (
            await self.get_playback_asset(
                ResolvedTrack(
                    track_ref=track_ref,
                    canonical_artist="Unknown",
                    canonical_title="Unknown",
                )
            )
        ).playback_url

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _request(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload, _ = await request_json(
            self.client,
            provider=self.provider_name,
            method="GET",
            url=f"{self.base_url}{path}",
            max_attempts=1,
            headers=headers,
            params=params,
        )
        return payload

    @classmethod
    def _normalize_track(cls, item: dict[str, Any]) -> TrackMetadata:
        track_id = item.get("id")
        title = item.get("title")
        user = item.get("user")
        artist = user.get("name") if isinstance(user, dict) else item.get("artist")
        duration_value = item.get("duration")
        duration = int(duration_value) if isinstance(duration_value, (int, float)) else 0
        metadata = {
            key: item[key]
            for key in ("genre", "mood", "permalink", "artwork")
            if item.get(key) is not None
        }
        return TrackMetadata(
            track_ref=f"audius:{track_id}" if isinstance(track_id, str) and track_id else "",
            title=title if isinstance(title, str) else "",
            artist=artist if isinstance(artist, str) else "",
            duration_seconds=duration,
            playable=bool(track_id and title and artist and duration > 0),
            metadata=metadata,
        )


def _provider_id(track_ref: str) -> str:
    return track_ref.removeprefix("audius:")


def _normalized_name(value: object) -> str:
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""
