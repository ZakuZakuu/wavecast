import asyncio

from wavecast.intelligence.models import TrackProposal
from wavecast.intelligence.resolution import (
    resolve_track_proposal,
    resolve_track_proposal_across_providers,
)
from wavecast.providers.contracts import AudioAsset, AudioAssetType, TrackMetadata
from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService


class CatalogFixture:
    def __init__(self) -> None:
        self.tracks = [
            TrackMetadata(
                track_ref="netease:jealousy",
                artist="3rd Coast",
                title="Jealousy",
                duration_seconds=180,
                playable=True,
            )
        ]

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        del query
        return self.tracks[:limit]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        return next(track for track in self.tracks if track.track_ref == track_ref)

    async def get_playback_asset(self, resolved_track: object) -> AudioAsset:
        return AudioAsset(
            asset_id=resolved_track.track_ref,
            asset_type=AudioAssetType.MUSIC,
            provider="netease",
            playback_url="https://sidecar.test/stream/jealousy",
            duration=180,
        )


class ResolutionFixture:
    def __init__(
        self,
        search_tracks: list[TrackMetadata],
        details: dict[str, TrackMetadata | Exception] | None = None,
    ) -> None:
        self.search_tracks = search_tracks
        self.details = details or {}

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        del query
        return self.search_tracks[:limit]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        detail = self.details.get(track_ref)
        if isinstance(detail, Exception):
            raise detail
        if detail is not None:
            return detail
        return next(track for track in self.search_tracks if track.track_ref == track_ref)

    async def get_playback_asset(self, resolved_track: object) -> AudioAsset:
        return AudioAsset(
            asset_id=resolved_track.track_ref,
            asset_type=AudioAssetType.MUSIC,
            provider="fixture",
            playback_url="https://sidecar.test/stream/track",
            duration=180,
        )


def test_ensemble_resolution_requires_exact_catalog_identity() -> None:
    retrieval = MusicRetrievalService(MusicProviderRegistry({"netease": CatalogFixture()}))

    resolved = asyncio.run(
        resolve_track_proposal_across_providers(
            retrieval,
            TrackProposal(artist="3rd Coast", title="Jealousy", confidence=0.9),
        )
    )
    unresolved = asyncio.run(
        resolve_track_proposal_across_providers(
            retrieval,
            TrackProposal(artist="3rd Coast", title="Jealousy (Live)", confidence=0.9),
        )
    )

    assert resolved is not None
    assert resolved.track_ref == "netease:jealousy"
    assert unresolved is None


def test_search_exact_unplayable_is_confirmed_by_playable_provider_detail() -> None:
    search_track = TrackMetadata(
        track_ref="netease:何何",
        artist="藤井風",
        title="何なんw",
        duration_seconds=321,
        playable=False,
    )
    detail = search_track.model_copy(update={"playable": True})
    provider = ResolutionFixture([search_track], {search_track.track_ref: detail})

    resolved = asyncio.run(
        resolve_track_proposal(
            provider,
            TrackProposal(artist="藤井風", title="何なんw", confidence=0.9),
        )
    )

    assert resolved is not None
    assert resolved.track_ref == "netease:何何"


def test_search_exact_unplayable_stays_unresolved_when_detail_is_unplayable() -> None:
    search_track = TrackMetadata(
        track_ref="netease:unavailable",
        artist="藤井風",
        title="死ぬのがいいわ",
        duration_seconds=186,
        playable=False,
    )
    provider = ResolutionFixture([search_track])

    resolved = asyncio.run(
        resolve_track_proposal(
            provider,
            TrackProposal(artist="藤井風", title="死ぬのがいいわ", confidence=0.9),
        )
    )

    assert resolved is None


def test_search_exact_unplayable_rejects_identity_changed_by_detail() -> None:
    search_track = TrackMetadata(
        track_ref="netease:cover",
        artist="藤井風",
        title="何なんw",
        duration_seconds=321,
        playable=False,
    )
    detail = TrackMetadata(
        track_ref=search_track.track_ref,
        artist="Another Artist",
        title="何なんw",
        duration_seconds=321,
        playable=True,
    )
    provider = ResolutionFixture([search_track], {search_track.track_ref: detail})

    resolved = asyncio.run(
        resolve_track_proposal(
            provider,
            TrackProposal(artist="藤井風", title="何なんw", confidence=0.9),
        )
    )

    assert resolved is None


def test_unrelated_first_result_does_not_block_later_exact_result() -> None:
    tracks = [
        TrackMetadata(
            track_ref="netease:other",
            artist="藤井風",
            title="まつり",
            duration_seconds=225,
            playable=True,
        ),
        TrackMetadata(
            track_ref="netease:target",
            artist="藤井風",
            title="何なんw",
            duration_seconds=321,
            playable=False,
        ),
    ]
    provider = ResolutionFixture(
        tracks,
        {"netease:target": tracks[1].model_copy(update={"playable": True})},
    )

    resolved = asyncio.run(
        resolve_track_proposal(
            provider,
            TrackProposal(artist="藤井風", title="何なんw", confidence=0.9),
        )
    )

    assert resolved is not None
    assert resolved.track_ref == "netease:target"


def test_cover_or_live_before_exact_original_does_not_get_selected() -> None:
    tracks = [
        TrackMetadata(
            track_ref="netease:live",
            artist="藤井風",
            title="死ぬのがいいわ (Live at Tiny Desk)",
            duration_seconds=186,
            playable=True,
        ),
        TrackMetadata(
            track_ref="netease:original",
            artist="藤井風",
            title="死ぬのがいいわ",
            duration_seconds=186,
            playable=False,
        ),
    ]
    provider = ResolutionFixture(
        tracks,
        {"netease:original": tracks[1].model_copy(update={"playable": True})},
    )
    retrieval = MusicRetrievalService(MusicProviderRegistry({"netease": provider}))

    resolved = asyncio.run(
        resolve_track_proposal_across_providers(
            retrieval,
            TrackProposal(artist="藤井風", title="死ぬのがいいわ", confidence=0.9),
        )
    )

    assert resolved is not None
    assert resolved.track_ref == "netease:original"


def test_provider_detail_error_isolated_from_another_provider() -> None:
    failing_track = TrackMetadata(
        track_ref="netease:target",
        artist="藤井風",
        title="何なんw",
        duration_seconds=321,
        playable=False,
    )
    healthy_track = TrackMetadata(
        track_ref="audius:target",
        artist="藤井風",
        title="何なんw",
        duration_seconds=321,
        playable=False,
    )
    failing = ResolutionFixture(
        [failing_track],
        {failing_track.track_ref: ProviderInvalidResponseError("malformed detail")},
    )
    healthy = ResolutionFixture(
        [healthy_track],
        {healthy_track.track_ref: healthy_track.model_copy(update={"playable": True})},
    )
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": failing, "audius": healthy})
    )

    resolved = asyncio.run(
        resolve_track_proposal_across_providers(
            retrieval,
            TrackProposal(artist="藤井風", title="何なんw", confidence=0.9),
        )
    )

    assert resolved is not None
    assert resolved.track_ref == "audius:target"
