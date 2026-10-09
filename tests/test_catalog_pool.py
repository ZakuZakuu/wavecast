import asyncio

import pytest
from wavecast.catalog_pool import (
    AvailabilityStatus,
    CatalogPoolBuilder,
    PoolBuildConfig,
    PoolSource,
    artist_credit_includes,
    primary_artist,
    split_artists,
)
from wavecast.intelligence.models import TrackProposal
from wavecast.providers.contracts import AudioAsset, AudioAssetType, TrackMetadata
from wavecast.providers.errors import ProviderInvalidResponseError, ProviderUnavailableError
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService


def track(
    ref: str, artist: str, title: str, *, playable: bool = True, seconds: int = 200
) -> TrackMetadata:
    return TrackMetadata(
        track_ref=f"netease:{ref}",
        artist=artist,
        title=title,
        duration_seconds=seconds,
        playable=playable,
    )


class SidecarLikeCatalog:
    """Like the real sidecar: search results never carry playability, detail does."""

    def __init__(
        self,
        tracks: list[TrackMetadata],
        results: dict[str, list[str]] | None = None,
        *,
        fail: set[str] = frozenset(),  # type: ignore[assignment]
        delays: dict[str, float] | None = None,
        fail_search: bool = False,
    ) -> None:
        self.fail_search = fail_search
        self.by_ref = {item.track_ref: item for item in tracks}
        self.results = results or {}
        self.fail = fail
        self.delays = delays or {}
        self.queries: list[str] = []
        self.detail_calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        self.queries.append(query)
        if self.fail_search:
            raise ProviderUnavailableError("music upstream unavailable")
        refs = self.results.get(query, [])
        return [
            self.by_ref[f"netease:{ref}"].model_copy(update={"playable": False})
            for ref in refs[:limit]
        ]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        self.detail_calls.append(track_ref)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delays.get(track_ref, 0.0))
            if track_ref in self.fail:
                raise ProviderInvalidResponseError("detail failed")
            return self.by_ref[track_ref]
        finally:
            self.active -= 1

    async def get_playback_asset(self, resolved_track: object) -> AudioAsset:
        return AudioAsset(
            asset_id="x",
            asset_type=AudioAssetType.MUSIC,
            provider="netease",
            playback_url="https://sidecar.test/x",
            duration=1,
        )


def builder(
    catalog: SidecarLikeCatalog, config: PoolBuildConfig | None = None
) -> CatalogPoolBuilder:
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": catalog}, preference=("netease",))
    )
    return CatalogPoolBuilder(retrieval, config)


def proposal(artist: str, title: str) -> TrackProposal:
    return TrackProposal(artist=artist, title=title, confidence=0.9)


def test_split_artists_uses_credit_separators_not_name_characters() -> None:
    assert split_artists("椎名林檎, TOWA TEI") == ("椎名林檎", "TOWA TEI")
    assert split_artists("A feat. B") == ("A", "B")
    assert split_artists("AC/DC") == ("AC/DC",)
    assert split_artists("X Japan") == ("X Japan",)
    assert split_artists("Simon & Garfunkel") == ("Simon & Garfunkel",)
    assert primary_artist("久石譲, 奥戸巴寿") == "久石譲"


def test_artist_credit_matches_script_variants_but_not_substrings() -> None:
    assert artist_credit_includes("久石譲, 奥戸巴寿", "久石让")
    assert artist_credit_includes("久石譲", "久石让")
    assert not artist_credit_includes("木村弓", "久石让")
    assert not artist_credit_includes("Bill Evans Trio", "Bill Evans")


def test_config_rejects_unbounded_or_invalid_values() -> None:
    with pytest.raises(ValueError):
        PoolBuildConfig(concurrency=0)
    with pytest.raises(ValueError):
        PoolBuildConfig(timeout_seconds=0)
    with pytest.raises(ValueError):
        PoolBuildConfig(max_verifications=-1)


def test_llm_candidates_are_classified_playable_unplayable_or_not_found() -> None:
    catalog = SidecarLikeCatalog(
        [
            track("1", "久石譲", "娜乌西卡安魂曲"),
            track("2", "椎名林檎", "本能", playable=False),
        ],
        {
            "久石让 娜乌西卡安魂曲": ["1"],
            "椎名林檎 本能": ["2"],
        },
    )

    pool = asyncio.run(
        builder(catalog).build(
            proposals=[
                proposal("久石让", "娜乌西卡安魂曲"),  # script variant of the catalog artist
                proposal("椎名林檎", "本能"),
                proposal("Nobody", "Nothing"),
            ]
        )
    )

    assert [entry.track_ref for entry in pool.entries] == ["netease:1"]
    assert pool.entries[0].artist == "久石譲"  # catalog spelling, not the proposer's
    assert pool.entries[0].source is PoolSource.LLM_CANDIDATE
    statuses = [outcome.status for outcome in pool.outcomes]
    assert statuses == [
        AvailabilityStatus.PLAYABLE,
        AvailabilityStatus.UNPLAYABLE,
        AvailabilityStatus.NOT_FOUND,
    ]
    assert pool.unplayable_artists() == ["椎名林檎"]


def test_llm_candidate_needs_exact_identity_not_a_similar_song() -> None:
    catalog = SidecarLikeCatalog(
        [track("1", "久石譲", "天空の城ラピュタ")],
        {"久石让 天空之城": ["1"], "天空之城": ["1"]},
    )

    pool = asyncio.run(builder(catalog).build(proposals=[proposal("久石让", "天空之城")]))

    assert pool.entries == []
    assert pool.outcomes[0].status is AvailabilityStatus.NOT_FOUND
    assert catalog.detail_calls == []


def test_artist_search_keeps_only_tracks_credited_to_that_artist() -> None:
    catalog = SidecarLikeCatalog(
        [
            track("1", "久石譲", "人生のメリーゴーランド"),
            track("2", "久石譲, 奥戸巴寿", "Spirited Away"),
            track("3", "木村弓", "いつも何度でも"),  # tribute artist
        ],
        {"久石让": ["1", "2", "3"]},
    )

    pool = asyncio.run(builder(catalog).build(artist_queries=["久石让"]))

    assert [entry.track_ref for entry in pool.entries] == ["netease:1", "netease:2"]
    assert {entry.source for entry in pool.entries} == {PoolSource.ARTIST_SEARCH}
    assert "netease:3" not in catalog.detail_calls  # irrelevant tracks are never verified
    assert [entry.primary_artist for entry in pool.entries] == ["久石譲", "久石譲"]


def test_keyword_entries_are_capped_and_ordered_after_trusted_sources() -> None:
    tracks = [
        track("llm", "Bill Evans", "Peace Piece"),
        track("art", "Bill Evans", "Waltz for Debby"),
        *[track(f"kw{i}", f"Channel {i}", f"Late Night Jazz {i}") for i in range(5)],
    ]
    catalog = SidecarLikeCatalog(
        tracks,
        {
            "Bill Evans Peace Piece": ["llm"],
            "Bill Evans": ["art"],
            "late night jazz": ["kw0", "kw1", "kw2", "kw3", "kw4"],
        },
    )

    pool = asyncio.run(
        builder(catalog, PoolBuildConfig(max_keyword_entries=2)).build(
            proposals=[proposal("Bill Evans", "Peace Piece")],
            artist_queries=["Bill Evans"],
            keyword_queries=["late night jazz"],
        )
    )

    assert [entry.source for entry in pool.entries] == [
        PoolSource.LLM_CANDIDATE,
        PoolSource.ARTIST_SEARCH,
        PoolSource.KEYWORD_SEARCH,
        PoolSource.KEYWORD_SEARCH,
    ]
    assert [entry.track_ref for entry in pool.entries][2:] == ["netease:kw0", "netease:kw1"]


def test_versions_are_excluded_and_a_song_found_twice_keeps_the_trusted_source() -> None:
    catalog = SidecarLikeCatalog(
        [
            track("1", "Artist", "Song"),
            track("2", "Artist", "Song - Live"),
            track("3", "Artist", "Song - Remix"),
            track("4", "Artist", "Other"),
        ],
        {"Artist": ["1", "2", "3"], "topic": ["1", "4"]},
    )

    pool = asyncio.run(builder(catalog).build(artist_queries=["Artist"], keyword_queries=["topic"]))

    assert [(entry.track_ref, entry.source) for entry in pool.entries] == [
        ("netease:1", PoolSource.ARTIST_SEARCH),
        ("netease:4", PoolSource.KEYWORD_SEARCH),
    ]
    assert catalog.detail_calls.count("netease:1") == 1
    assert "netease:2" not in catalog.detail_calls
    assert "netease:3" not in catalog.detail_calls


def test_verification_budget_and_concurrency_are_respected() -> None:
    tracks = [track(str(i), f"Artist {i}", f"Song {i}") for i in range(10)]
    catalog = SidecarLikeCatalog(
        tracks,
        {"topic": [str(i) for i in range(10)]},
        delays={item.track_ref: 0.01 for item in tracks},
    )

    pool = asyncio.run(
        builder(catalog, PoolBuildConfig(max_verifications=4, concurrency=2)).build(
            keyword_queries=["topic"]
        )
    )

    assert len(catalog.detail_calls) == 4
    assert catalog.max_active <= 2
    assert pool.verification_count == 4
    assert len(pool.entries) == 4


def test_a_provider_error_is_recorded_and_does_not_stop_the_build() -> None:
    catalog = SidecarLikeCatalog(
        [track("1", "A", "One"), track("2", "B", "Two")],
        {"topic": ["1", "2"]},
        fail={"netease:1"},
    )

    pool = asyncio.run(builder(catalog).build(keyword_queries=["topic"]))

    assert [entry.track_ref for entry in pool.entries] == ["netease:2"]
    assert pool.count(AvailabilityStatus.PROVIDER_ERROR) == 1
    assert pool.unplayable_artists() == []  # an outage is not evidence of unavailability


def test_timeout_returns_the_partial_pool_marked_truncated() -> None:
    tracks = [track(str(i), f"Artist {i}", f"Song {i}") for i in range(6)]
    catalog = SidecarLikeCatalog(
        tracks,
        {"topic": [str(i) for i in range(6)]},
        delays={item.track_ref: 0.05 for item in tracks},
    )

    pool = asyncio.run(
        builder(catalog, PoolBuildConfig(concurrency=1, timeout_seconds=0.14)).build(
            keyword_queries=["topic"]
        )
    )

    assert pool.truncated
    assert 0 < len(pool.entries) < 6


def test_output_order_follows_input_order_not_completion_order() -> None:
    tracks = [track(str(i), f"Artist {i}", f"Song {i}") for i in range(4)]
    catalog = SidecarLikeCatalog(
        tracks,
        {"topic": ["0", "1", "2", "3"]},
        delays={"netease:0": 0.05, "netease:1": 0.0, "netease:2": 0.03, "netease:3": 0.0},
    )

    pool = asyncio.run(
        builder(catalog, PoolBuildConfig(concurrency=4)).build(keyword_queries=["topic"])
    )

    assert [entry.track_ref for entry in pool.entries] == [f"netease:{i}" for i in range(4)]


def test_summary_contains_counts_only() -> None:
    catalog = SidecarLikeCatalog([track("1", "A", "One")], {"topic": ["1"]})

    summary = asyncio.run(builder(catalog).build(keyword_queries=["topic"])).summary()

    assert summary["entries"] == 1
    assert summary["by_source"] == {"llm_candidate": 0, "artist_search": 0, "keyword_search": 1}
    assert "track_ref" not in str(summary)


def test_a_song_with_several_catalog_entries_is_playable_if_any_entry_plays() -> None:
    catalog = SidecarLikeCatalog(
        [
            track("a1", "椎名林檎", "罪と罰", playable=False),
            track("a2", "椎名林檎", "罪と罰", playable=False),
            track("a3", "椎名林檎", "罪と罰", playable=True),
        ],
        {"椎名林檎": ["a1", "a2", "a3"]},
    )

    pool = asyncio.run(builder(catalog).build(artist_queries=["椎名林檎"]))

    assert [entry.track_ref for entry in pool.entries] == ["netease:a3"]
    assert catalog.detail_calls == ["netease:a1", "netease:a2", "netease:a3"]
    assert pool.unplayable_artists() == []


def test_attempts_per_song_are_bounded_and_the_song_is_then_reported_unplayable() -> None:
    catalog = SidecarLikeCatalog(
        [
            *[track(f"u{i}", "椎名林檎", "本能", playable=False) for i in range(3)],
            track("z-late", "椎名林檎", "本能", playable=True),
        ],
        {"椎名林檎": ["u0", "u1", "u2", "z-late"]},
    )

    pool = asyncio.run(
        builder(catalog, PoolBuildConfig(max_refs_per_song=3)).build(artist_queries=["椎名林檎"])
    )

    assert pool.entries == []
    assert len(catalog.detail_calls) == 3
    assert pool.unplayable_artists() == ["椎名林檎"]


def test_a_song_judged_unplayable_through_an_llm_candidate_is_not_verified_again() -> None:
    catalog = SidecarLikeCatalog(
        [track("1", "椎名林檎", "本能", playable=False)],
        {"椎名林檎 本能": ["1"], "椎名林檎": ["1"]},
    )

    pool = asyncio.run(
        builder(catalog).build(
            proposals=[proposal("椎名林檎", "本能")], artist_queries=["椎名林檎"]
        )
    )

    assert catalog.detail_calls == ["netease:1"]
    assert pool.count(AvailabilityStatus.UNPLAYABLE) == 1


def test_config_rejects_zero_attempts_per_song() -> None:
    with pytest.raises(ValueError):
        PoolBuildConfig(max_refs_per_song=0)


def test_a_failed_search_is_a_provider_error_not_a_missing_track() -> None:
    catalog = SidecarLikeCatalog([track("1", "A", "One")], {"A One": ["1"]}, fail_search=True)

    pool = asyncio.run(builder(catalog).build(proposals=[proposal("A", "One")]))

    assert pool.entries == []
    assert pool.outcomes[0].status is AvailabilityStatus.PROVIDER_ERROR
    assert pool.search_failure_count > 0
    assert pool.count(AvailabilityStatus.NOT_FOUND) == 0


def test_one_song_listed_with_reordered_credits_and_a_feature_suffix_is_a_single_entry() -> None:
    catalog = SidecarLikeCatalog(
        [
            track("1", "椎名林檎, TOWA TEI", "APPLE"),
            track("2", "TOWA TEI, 椎名林檎", "APPLE (feat. 椎名林檎)"),
            track("3", "椎名林檎, TOWA TEI", "Different Song"),
        ],
        {"椎名林檎": ["1", "2", "3"]},
    )

    pool = asyncio.run(builder(catalog).build(artist_queries=["椎名林檎"]))

    titles = [entry.title for entry in pool.entries]
    assert len(titles) == 2
    assert "Different Song" in titles
    assert sum(title.startswith("APPLE") for title in titles) == 1  # one entry per song
    assert len(catalog.detail_calls) == 2  # the second listing was never verified


def test_a_song_listed_with_and_without_accents_is_a_single_entry() -> None:
    catalog = SidecarLikeCatalog(
        [
            track("1", "Pablo Casals", "Suite No. 1: I. Prélude"),
            track("2", "Pablo Casals", "Suite No. 1: I. Prelude"),
            track("3", "Pablo Casals", "Suite No. 1: IV. Sarabande"),
        ],
        {"Pablo Casals": ["1", "2", "3"]},
    )

    pool = asyncio.run(builder(catalog).build(artist_queries=["Pablo Casals"]))

    assert len(pool.entries) == 2
    assert len(catalog.detail_calls) == 2
