"""The album artwork of the song that is playing follows the song from the catalog to the segment."""

import asyncio

import httpx
from wavecast.catalog_pool import CatalogPoolBuilder, PoolBuildConfig
from wavecast.intelligence.models import ResolvedTrack
from wavecast.intelligence.resolution import _resolved_track, music_segment_from_track
from wavecast.models.episode import CoverParams, MusicSegment
from wavecast.proposals import ProgramProposal
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import TrackMetadata
from wavecast.providers.netease import NeteaseMusicProvider
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService
from wavecast.spoken_form import catalog_cover

from tests.test_catalog_pool import SidecarLikeCatalog

COVER = "https://p1.music.126.net/abc/123.jpg"


def _song(**metadata: object) -> TrackMetadata:
    return TrackMetadata(
        track_ref="netease:1",
        title="春风吹",
        artist="方大同",
        duration_seconds=240,
        playable=True,
        metadata=dict(metadata),
    )


def test_only_a_web_address_is_taken_as_a_cover() -> None:
    assert catalog_cover({"cover_url": COVER}) == COVER
    assert catalog_cover({"cover_url": f"  {COVER} "}) == COVER
    assert catalog_cover({"cover_url": "http://p1.music.126.net/a.jpg"}) is None
    assert catalog_cover({"cover_url": "javascript:alert(1)"}) is None
    assert catalog_cover({"cover_url": "https://x/" + "a" * 500}) is None
    assert catalog_cover({"cover_url": 5}) is None
    assert catalog_cover({}) is None
    assert catalog_cover(None) is None


def test_the_sidecar_adapter_keeps_the_cover_in_track_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tracks": [
                    {
                        "id": "1",
                        "artist": "方大同",
                        "title": "春风吹",
                        "duration_seconds": 240,
                        "cover_url": COVER,
                    },
                    {"id": "2", "artist": "方大同", "title": "爱爱爱", "duration_seconds": 200},
                ]
            },
        )

    async def run() -> list[TrackMetadata]:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://netease.sidecar"
        )
        provider = NeteaseMusicProvider(
            ProviderSettings(), client=client, base_url="https://netease.sidecar"
        )
        found = await provider.search("方大同", limit=2)
        await client.aclose()
        return found

    tracks = asyncio.run(run())

    assert tracks[0].metadata["cover_url"] == COVER
    assert "cover_url" not in tracks[1].metadata


def test_a_resolved_track_and_its_segment_carry_the_cover() -> None:
    resolved = _resolved_track(_song(cover_url=COVER))
    assert resolved is not None and resolved.cover_url == COVER

    segment = music_segment_from_track(resolved, chapter_id="chapter-1", order=1)
    assert isinstance(segment, MusicSegment) and segment.cover_url == COVER

    plain = _resolved_track(_song())
    assert plain is not None and plain.cover_url is None
    assert music_segment_from_track(plain, chapter_id="chapter-1", order=1).cover_url is None


def test_a_pool_entry_keeps_the_cover_into_the_resolved_track() -> None:
    catalog = SidecarLikeCatalog([_song(cover_url=COVER)], {"方大同": ["1"]})
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": catalog}, preference=("netease",))
    )

    pool = asyncio.run(
        CatalogPoolBuilder(retrieval, PoolBuildConfig(search_limit=5)).build(
            artist_queries=["方大同"]
        )
    )

    assert pool.entries[0].resolved_track().cover_url == COVER


def test_the_cover_survives_proposal_and_seed() -> None:
    proposal = ProgramProposal(
        id="p1",
        title="方大同",
        topic="方大同",
        short_description="A route",
        estimated_duration_seconds=1800,
        opening_track_ref="netease:1",
        opening_track_title="春风吹",
        opening_track_artist="方大同",
        opening_track_cover_url=COVER,
        cover=CoverParams(family="editorial", seed=1, palette=("#102030", "#f0a050")),
        editorial_route=["opening", "discovery"],
    )
    seed = proposal.to_episode_seed()

    assert seed.opening_track_cover_url == COVER
    assert ProgramProposal.from_episode_seed(seed).opening_track_cover_url == COVER


def test_a_track_without_a_cover_is_still_a_valid_track() -> None:
    track = ResolvedTrack(track_ref="netease:1", canonical_artist="a", canonical_title="b")
    assert track.cover_url is None
