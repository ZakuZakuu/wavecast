import asyncio

import pytest
from wavecast.providers.contracts import AudioAsset, AudioAssetType, TrackMetadata
from wavecast.providers.errors import ProviderConfigurationError, ProviderInvalidResponseError
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import (
    MusicRetrievalService,
    RetrievedTrack,
    VersionKind,
)


class FixtureMusicProvider:
    def __init__(self, name: str, tracks: list[TrackMetadata], *, failure: Exception | None = None):
        self.provider_name = name
        self.tracks = tracks
        self.failure = failure

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        del query
        if self.failure:
            raise self.failure
        return self.tracks[:limit]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        return next(track for track in self.tracks if track.track_ref == track_ref)

    async def get_playback_asset(self, resolved_track: object) -> AudioAsset:
        metadata = await self.resolve_track(resolved_track.track_ref)
        return AudioAsset(
            asset_id=metadata.track_ref,
            asset_type=AudioAssetType.MUSIC,
            provider=self.provider_name,
            playback_url=f"mock://{metadata.track_ref}",
            duration=metadata.duration_seconds,
        )


def metadata(
    ref: str,
    artist: str,
    title: str,
    *,
    duration: int = 180,
    album: str | None = "Album",
    playable: bool = True,
    **extra: object,
) -> TrackMetadata:
    values = {"album": album, **extra}
    return TrackMetadata(
        track_ref=ref,
        artist=artist,
        title=title,
        duration_seconds=duration,
        playable=playable,
        metadata={key: value for key, value in values.items() if value is not None},
    )


def service(*providers: FixtureMusicProvider, timeout: float = 0.2) -> MusicRetrievalService:
    return MusicRetrievalService(
        MusicProviderRegistry({provider.provider_name: provider for provider in providers}),
        per_provider_timeout_seconds=timeout,
    )


def test_retrieval_preserves_versions_and_provider_alternatives() -> None:
    first = FixtureMusicProvider(
        "netease",
        [
            metadata("netease:jealousy", "3rd Coast", "Jealousy"),
            metadata("netease:jealousy-live", "3rd Coast", "Jealousy (Live at Seoul)"),
            metadata("netease:jealousy-remix", "3rd Coast", "Jealousy - Remix"),
        ],
    )
    second = FixtureMusicProvider(
        "qqmusic",
        [metadata("qqmusic:jealousy", "3rd Coast", "Jealousy")],
    )

    report = asyncio.run(
        service(first, second).search_report(
            "3rd Coast Jealousy",
            requested_artist="3rd Coast",
            requested_title="Jealousy",
            limit=10,
        )
    )

    assert len(report.candidates) == 4
    assert {candidate.version_kind for candidate in report.candidates} == {
        VersionKind.UNKNOWN,
        VersionKind.LIVE,
        VersionKind.REMIX,
    }
    assert not any(
        candidate.version_kind is VersionKind.STUDIO for candidate in report.candidates
    )
    studio_group = next(
        group for group in report.groups if {candidate.version_kind for candidate in group.candidates} == {VersionKind.UNKNOWN}
    )
    assert {candidate.provider for candidate in studio_group.candidates} == {"netease", "qqmusic"}
    assert len(report.groups) == 3


def test_retrieval_ranking_is_explainable_and_not_provider_order() -> None:
    broad = FixtureMusicProvider(
        "audius",
        [metadata("audius:other", "Other Artist", "Jealousy", playable=True)],
    )
    exact = FixtureMusicProvider(
        "qqmusic",
        [metadata("qqmusic:exact", "3rd Coast", "Jealousy", playable=True)],
    )

    candidates = asyncio.run(
        service(broad, exact).search(
            "3rd Coast Jealousy",
            requested_artist="3rd Coast",
            requested_title="Jealousy",
            limit=2,
        )
    )

    assert candidates[0].track_ref == "qqmusic:exact"
    assert candidates[0].score > candidates[1].score
    assert "exact_artist" in candidates[0].ranking_reasons
    assert "exact_title" in candidates[0].ranking_reasons
    assert "provider_priority" in candidates[0].ranking_reasons


def test_retrieval_isolates_timeout_and_malformed_provider() -> None:
    class SlowProvider(FixtureMusicProvider):
        async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
            del query, limit
            await asyncio.sleep(0.05)
            return []

    class MalformedProvider(FixtureMusicProvider):
        async def search(self, query: str, *, limit: int = 5) -> list[object]:
            del query, limit
            return [{"not": "a track"}]

    healthy = FixtureMusicProvider(
        "mock",
        [metadata("mock:healthy", "Healthy Artist", "Healthy Song")],
    )
    report = asyncio.run(
        service(
            SlowProvider("slow", []),
            FixtureMusicProvider("broken", [], failure=ProviderInvalidResponseError("bad JSON")),
            MalformedProvider("malformed", []),
            healthy,
            timeout=0.01,
        ).search_report("Healthy Song", limit=5)
    )

    assert [candidate.track_ref for candidate in report.candidates] == ["mock:healthy"]
    assert {failure.provider for failure in report.failures} == {
        "slow",
        "broken",
        "malformed",
    }
    assert {failure.kind for failure in report.failures} == {
        "timeout",
        "provider_error",
        "malformed_result",
    }


def test_retrieved_track_version_parser_is_conservative() -> None:
    assert RetrievedTrack.version_for("Song", {}) == (VersionKind.UNKNOWN, None, "Song")
    assert RetrievedTrack.version_for("Song (Live at Seoul)", {})[0] is VersionKind.LIVE
    assert RetrievedTrack.version_for("Song - Remix", {})[0] is VersionKind.REMIX
    assert RetrievedTrack.version_for("Song (Acoustic)", {})[0] is VersionKind.ACOUSTIC
    assert RetrievedTrack.version_for("Song (Radio Edit)", {})[0] is VersionKind.RADIO_EDIT
    assert RetrievedTrack.version_for("Song", {"soundtrack": "Persona 4 OST"})[0] is VersionKind.OST


def test_registry_orders_providers_and_routes_provider_qualified_playback() -> None:
    qqmusic = FixtureMusicProvider(
        "qqmusic", [metadata("qqmusic:track-1", "Artist", "Song")]
    )
    audius = FixtureMusicProvider("audius", [metadata("audius:track-1", "Artist", "Song")])
    registry = MusicProviderRegistry(
        {"qqmusic": qqmusic, "audius": audius}, preference=["audius", "qqmusic"]
    )

    assert [name for name, _provider in registry.ordered()] == ["audius", "qqmusic"]
    assert registry.provider_for_track_ref("qqmusic:track-1") is qqmusic
    asset = asyncio.run(
        registry.get_playback_asset(
            type("Resolved", (), {"track_ref": "qqmusic:track-1"})()
        )
    )
    assert asset.provider == "qqmusic"
    with pytest.raises(ProviderConfigurationError):
        registry.provider_for_track_ref("unknown:track-1")
