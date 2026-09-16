import asyncio

from wavecast.intelligence.models import TrackProposal
from wavecast.intelligence.resolution import resolve_track_proposal_across_providers
from wavecast.providers.contracts import AudioAsset, AudioAssetType, TrackMetadata
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
