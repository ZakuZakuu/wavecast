"""The catalog's own Chinese title for a song is what the voice says in place of the original."""

import asyncio

import httpx
from wavecast.catalog_pool import CatalogPoolBuilder, PoolBuildConfig
from wavecast.intelligence.models import OutputLanguage, ResolvedTrack
from wavecast.intelligence.resolution import _resolved_track
from wavecast.proposals import ProposalGenerationRequest, _opening_copy
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import TrackMetadata
from wavecast.providers.netease import NeteaseMusicProvider
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService
from wavecast.spoken_form import KnownTrack, chinese_title, to_spoken_form
from wavecast.stations import StationId

from tests.test_catalog_pool import SidecarLikeCatalog
from tests.test_program_proposals import _english_request_draft_batch

# --- reading the catalog's title --------------------------------------------------------------


def test_only_a_readable_chinese_title_is_used() -> None:
    assert chinese_title({"title_zh": "回到那个夏天"}) == "回到那个夏天"
    assert chinese_title({"title_zh": "風のとおり道"}) is None  # kana: not readable
    assert chinese_title({"title_zh": ""}) is None
    assert chinese_title({"title_zh": 5}) is None
    assert chinese_title({}) is None and chinese_title(None) is None


def test_the_sidecar_adapter_keeps_the_chinese_title() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tracks": [
                    {
                        "id": "1",
                        "artist": "久石譲",
                        "title": "あの夏へ",
                        "duration_seconds": 190,
                        "tns": ["回到那个夏天"],
                    }
                ]
            },
        )

    provider = NeteaseMusicProvider(
        ProviderSettings(netease_music_api_base_url="https://netease.sidecar"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    tracks = asyncio.run(provider.search("あの夏へ", limit=3))

    assert chinese_title(tracks[0].metadata) == "回到那个夏天"


# --- it follows the song ---------------------------------------------------------------------


def test_a_resolved_track_carries_the_chinese_title() -> None:
    metadata = TrackMetadata(
        track_ref="netease:1",
        title="あの夏へ",
        artist="久石譲",
        duration_seconds=190,
        playable=True,
        metadata={"title_zh": "回到那个夏天"},
    )

    assert _resolved_track(metadata).spoken_title == "回到那个夏天"  # type: ignore[union-attr]


def test_a_pool_entry_keeps_the_chinese_title_into_the_resolved_track() -> None:
    song = TrackMetadata(
        track_ref="netease:1",
        title="あの夏へ",
        artist="久石譲",
        duration_seconds=190,
        playable=True,
        metadata={"title_zh": "回到那个夏天"},
    )
    catalog = SidecarLikeCatalog([song], {"久石譲": ["1"]})
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": catalog}, preference=("netease",))
    )

    pool = asyncio.run(
        CatalogPoolBuilder(retrieval, PoolBuildConfig(search_limit=5)).build(
            artist_queries=["久石譲"]
        )
    )

    assert pool.entries[0].resolved_track().spoken_title == "回到那个夏天"


# --- what the voice says ---------------------------------------------------------------------


def test_the_voice_says_the_catalogs_chinese_title_instead_of_the_original() -> None:
    with_title = KnownTrack(artist="久石譲", title="あの夏へ", spoken_title="回到那个夏天")
    without = KnownTrack(artist="久石譲", title="あの夏へ")

    said = to_spoken_form("先来听《あの夏へ》，久石譲的。", [with_title])
    fallback = to_spoken_form("先来听《あの夏へ》，久石譲的。", [without])

    assert said.ok and "回到那个夏天" in said.tts_text and "あの夏へ" not in said.tts_text
    assert fallback.ok and "这首歌" in fallback.tts_text


def _opening(track: ResolvedTrack, station: StationId = StationId.PORTRAIT) -> str:
    draft = _english_request_draft_batch().proposals[0]
    request = ProposalGenerationRequest(
        prompt="久石让", output_language=OutputLanguage.ZH_CN, station=station
    )
    return _opening_copy(request, draft, track)[0]


def test_the_opening_says_the_chinese_title_when_the_catalog_has_one() -> None:
    track = ResolvedTrack(
        track_ref="netease:1",
        canonical_artist="久石譲",
        canonical_title="あの夏へ",
        spoken_title="回到那个夏天",
    )

    text = _opening(track)

    assert "回到那个夏天" in text and "あの夏へ" not in text
    assert "久石让" in text  # the artist is said in simplified characters


def test_the_opening_never_contains_text_the_voice_cannot_read() -> None:
    track = ResolvedTrack(
        track_ref="netease:1", canonical_artist="久石譲", canonical_title="あの夏へ"
    )

    text = _opening(track)

    assert "这首歌" in text and "《这首歌》" not in text
    assert not any("぀" <= char <= "ヿ" for char in text)
