"""Small HTTP contract for optional music catalog sidecars.

The sidecars are deliberately treated as external services.  This adapter does not
embed NetEase/QQ platform protocols; both services expose the same WaveCast-facing
JSON shape at configurable endpoints.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from wavecast.audio_timing import TrackTimingProfile, track_timing_profile_from_payload

from .config import ProviderSettings
from .contracts import AudioAsset, AudioAssetType, MusicProvider, TrackMetadata
from .errors import ProviderConfigurationError, ProviderError, ProviderInvalidResponseError
from .http import request_json
from .playback import ResolvedPlaybackRequest

if TYPE_CHECKING:
    from wavecast.intelligence.models import ResolvedTrack


TIMING_PROFILE_TIMEOUT_SECONDS = 1.5


class SidecarMusicProvider(MusicProvider):
    """Provider-neutral adapter for a configured catalog HTTP sidecar."""

    provider_name: str
    track_ref_prefix: str
    timing_profile_path_enabled: bool = False

    def __init__(
        self,
        settings: ProviderSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
    ) -> None:
        settings = settings or ProviderSettings()
        configured_url = base_url or self._base_url_from_settings(settings)
        if not configured_url:
            raise ProviderConfigurationError(
                f"{self.provider_name} sidecar requires a configured base URL"
            )
        self.settings = settings
        self.base_url = configured_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=settings.timeout_seconds)
        self._owns_client = client is None

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        payload = await self._request("/search", params={"query": query, "limit": limit})
        return [self._normalize_track(item) for item in _track_items(payload)]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        provider_id = _provider_id(track_ref, self.track_ref_prefix)
        payload = await self._request(f"/tracks/{quote(provider_id, safe='')}")
        items = _track_items(payload)
        if not items:
            raise ProviderInvalidResponseError(f"{self.provider_name} returned no track metadata")
        return self._normalize_track(items[0])

    async def get_playback_asset(self, resolved_track: ResolvedTrack) -> AudioAsset:
        metadata = await self.resolve_track(resolved_track.track_ref)
        upstream_url = await self._resolve_upstream_playback_url(metadata)
        if not upstream_url or not metadata.playable:
            raise ProviderInvalidResponseError(
                f"{self.provider_name} returned an unplayable track asset"
            )
        return AudioAsset(
            asset_id=metadata.track_ref,
            asset_type=AudioAssetType.MUSIC,
            provider=self.provider_name,
            playback_url=self.playback_proxy_url(metadata.track_ref),
            duration=metadata.duration_seconds,
            metadata=_safe_metadata(metadata.metadata),
        )

    async def get_timing_profile(
        self, track_ref: str
    ) -> TrackTimingProfile | None:
        if not self.timing_profile_path_enabled:
            return None
        provider_id = _provider_id(track_ref, self.track_ref_prefix)
        try:
            payload = await asyncio.wait_for(
                self._request(f"/tracks/{quote(provider_id, safe='')}/timing"),
                timeout=TIMING_PROFILE_TIMEOUT_SECONDS,
            )
        except (TimeoutError, ProviderError):
            return None
        return track_timing_profile_from_payload(payload)

    async def resolve_upstream_playback_url(self, track_ref: str) -> str:
        """Resolve the current sidecar URL without exposing it to the browser."""
        request = await self.resolve_upstream_playback_request(track_ref)
        return request.url

    async def resolve_upstream_playback_request(
        self, track_ref: str
    ) -> ResolvedPlaybackRequest:
        """Resolve a provider request shared by browser and snapshot playback."""
        metadata = await self.resolve_track(track_ref)
        playback_url = await self._resolve_upstream_playback_url(metadata)
        if not playback_url or not metadata.playable:
            raise ProviderInvalidResponseError(
                f"{self.provider_name} returned an unplayable track asset"
            )
        return ResolvedPlaybackRequest(provider=self.provider_name, url=playback_url)

    def playback_proxy_url(self, track_ref: str) -> str:
        provider_id = _provider_id(track_ref, self.track_ref_prefix)
        return (
            f"/api/audio/sidecar/{self.provider_name}/"
            f"{quote(provider_id, safe='')}"
        )

    async def _resolve_upstream_playback_url(self, metadata: TrackMetadata) -> str | None:
        playback_url = _string_value(metadata.metadata.get("playback_url"))
        if not playback_url:
            provider_id = _provider_id(metadata.track_ref, self.track_ref_prefix)
            payload = await self._request(f"/tracks/{quote(provider_id, safe='')}/playback")
            playback_url = _playback_url(payload)
        return playback_url

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _request(
        self, path: str, *, params: dict[str, object] | None = None
    ) -> dict[str, Any]:
        payload, _response = await request_json(
            self.client,
            provider=self.provider_name,
            method="GET",
            url=f"{self.base_url}{path}",
            max_attempts=1,
            headers=self._request_headers(),
            params=params,
        )
        return payload

    def _request_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _base_url_from_settings(self, settings: ProviderSettings) -> str | None:
        raise NotImplementedError

    def _normalize_track(self, item: dict[str, Any]) -> TrackMetadata:
        raw_ref = _string_value(item.get("track_ref")) or _string_value(item.get("id")) or ""
        track_ref = (
            raw_ref
            if raw_ref.startswith(f"{self.track_ref_prefix}:")
            else f"{self.track_ref_prefix}:{raw_ref}"
        )
        artist = _string_value(item.get("artist")) or _nested_name(item.get("artists"))
        title = _string_value(item.get("title")) or ""
        duration = _duration(item.get("duration_seconds", item.get("duration")))
        raw_metadata = item.get("metadata")
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        for key in ("album", "playback_url", "stream_url", "version_kind", "version_label"):
            if item.get(key) is not None:
                metadata[key] = item[key]
        return TrackMetadata(
            track_ref=track_ref,
            title=title,
            artist=artist or "",
            duration_seconds=duration,
            playable=bool(item.get("playable", bool(raw_ref and title and artist and duration > 0))),
            metadata=metadata,
        )


def _track_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("tracks", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
    if any(key in payload for key in ("id", "track_ref", "title")):
        return [payload]
    return []


def _playback_url(payload: dict[str, Any]) -> str | None:
    for item in _track_items(payload):
        for key in ("playback_url", "stream_url", "url"):
            value = _string_value(item.get(key))
            if value:
                return value
    return None


def _provider_id(track_ref: str, prefix: str) -> str:
    return track_ref.removeprefix(f"{prefix}:")


def _string_value(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key not in {"playback_url", "stream_url", "url"}
    }


def _duration(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if isinstance(value, str):
        try:
            return max(0, int(float(value)))
        except ValueError:
            return 0
    return 0


def _nested_name(value: object) -> str | None:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return _string_value(value[0].get("name") or value[0].get("artist"))
    if isinstance(value, dict):
        return _string_value(value.get("name") or value.get("artist"))
    return None
