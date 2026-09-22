"""Audius catalog adapter with server-owned playback credentials.

Audius API keys identify an application and are sent as the ``api_key`` request
parameter. A bearer token is a separate backend-only credential and is sent in
``Authorization``. Browser playback receives a Wavecast proxy URL, never either
credential.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from .config import ProviderSettings
from .contracts import AudioAsset, AudioAssetType, TrackMetadata
from .errors import ProviderConfigurationError, ProviderInvalidResponseError
from .http import request_json
from .playback import ResolvedPlaybackRequest

if TYPE_CHECKING:
    from wavecast.intelligence.models import ResolvedTrack


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
        bearer_token: str | None = None,
        playback_proxy_base_url: str = "/api/audio/audius",
    ) -> None:
        settings = settings or ProviderSettings()
        self.settings = settings
        self.base_url = (base_url or settings.audius_base_url or self.default_base_url).rstrip("/")
        self.api_key = settings.audius_api_key if api_key is None else api_key
        self.bearer_token = (
            settings.audius_bearer_token if bearer_token is None else bearer_token
        )
        self.playback_proxy_base_url = playback_proxy_base_url.rstrip("/")
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

    async def get_playback_asset(self, resolved_track: ResolvedTrack) -> AudioAsset:
        track_ref = resolved_track.track_ref
        metadata = await self.resolve_track(track_ref)
        if not metadata.playable:
            raise ProviderInvalidResponseError("audius track has no playable duration")
        audius_id = _provider_id(metadata.track_ref)
        return AudioAsset(
            asset_id=metadata.track_ref,
            asset_type=AudioAssetType.MUSIC,
            provider=self.provider_name,
            # A browser audio element cannot safely carry a backend bearer token.
            playback_url=f"{self.playback_proxy_base_url}/{quote(audius_id, safe='')}",
            duration=metadata.duration_seconds,
            metadata=metadata.metadata,
        )

    async def resolve_upstream_playback_request(
        self, track_id: str
    ) -> ResolvedPlaybackRequest:
        """Build the credentialed upstream stream request for server-side consumers."""
        if self.settings.mode != "live" or not (self.api_key or self.bearer_token):
            raise ProviderConfigurationError("audius playback is not configured")
        headers = {"Accept": "audio/mpeg"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        params = {"api_key": self.api_key} if self.api_key else {}
        return ResolvedPlaybackRequest(
            provider=self.provider_name,
            url=f"{self.base_url}/tracks/{quote(track_id, safe='')}/stream",
            headers=headers,
            params=params,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _request(
        self, path: str, *, params: dict[str, object] | None = None
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        request_params = dict(params or {})
        if self.api_key:
            # The official SDK appends api_key to the request URL. It is not a
            # bearer token and must never be placed in Authorization.
            request_params["api_key"] = self.api_key
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        payload, _ = await request_json(
            self.client,
            provider=self.provider_name,
            method="GET",
            url=f"{self.base_url}{path}",
            max_attempts=1,
            headers=headers,
            params=request_params,
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
