"""Deterministic routing for provider-qualified music identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from inspect import isawaitable
from typing import TYPE_CHECKING

from .contracts import AudioAsset, MusicProvider, TrackMetadata
from .errors import ProviderConfigurationError

if TYPE_CHECKING:
    from wavecast.intelligence.models import ResolvedTrack


class MusicProviderRegistry:
    """Name/prefix lookup and playback routing without provider-specific runtime logic."""

    def __init__(
        self,
        providers: Mapping[str, MusicProvider] | None = None,
        *,
        preference: Sequence[str] = (),
    ) -> None:
        self.providers = dict(providers or {})
        self.preference = tuple(preference)

    def get(self, name: str) -> MusicProvider:
        normalized = name.casefold()
        for provider_name, provider in self.providers.items():
            if provider_name.casefold() == normalized:
                return provider
        raise ProviderConfigurationError(f"music provider is not configured: {name}")

    def provider_for_track_ref(self, track_ref: str) -> MusicProvider:
        provider_name, separator, _provider_id = track_ref.partition(":")
        if not separator or not provider_name:
            raise ProviderConfigurationError(
                f"track reference must be provider-qualified: {track_ref}"
            )
        return self.get(provider_name)

    def ordered(self) -> list[tuple[str, MusicProvider]]:
        ordered_names: list[str] = []
        for name in (*self.preference, *self.providers.keys()):
            if any(existing.casefold() == name.casefold() for existing in ordered_names):
                continue
            if any(configured.casefold() == name.casefold() for configured in self.providers):
                ordered_names.append(name)
        return [(name, self.get(name)) for name in ordered_names]

    async def resolve_track(self, resolved_track: ResolvedTrack) -> TrackMetadata:
        return await self.provider_for_track_ref(resolved_track.track_ref).resolve_track(
            resolved_track.track_ref
        )

    async def get_playback_asset(self, resolved_track: ResolvedTrack) -> AudioAsset:
        return await self.provider_for_track_ref(resolved_track.track_ref).get_playback_asset(
            resolved_track
        )

    async def aclose(self) -> None:
        """Close each unique configured provider client at most once."""
        closed: set[int] = set()
        for provider in self.providers.values():
            if id(provider) in closed:
                continue
            closed.add(id(provider))
            close = getattr(provider, "aclose", None)
            if not callable(close):
                continue
            result = close()
            if isawaitable(result):
                await result
