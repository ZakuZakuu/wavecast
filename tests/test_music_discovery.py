"""Finding a genre's artists through the catalog, without a model remembering them."""

import asyncio

from wavecast.catalog_pool import (
    AvailabilityStatus,
    CatalogPoolBuilder,
    PoolBuildConfig,
    PoolSource,
)
from wavecast.music_discovery import artist_scores, catalog_queries
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService

from tests.test_catalog_pool import SidecarLikeCatalog, track

# --- queries --------------------------------------------------------------------------------


def test_a_genre_request_searches_the_genre_not_the_sentence() -> None:
    queries = catalog_queries("想听点后摇")

    assert queries[0] == "后摇"
    assert "post-rock" in queries
    assert "后摇 乐队" in queries
    assert "想听点后摇" not in queries


def test_the_rest_of_the_request_is_kept_as_a_query() -> None:
    queries = catalog_queries("来点日本的后摇")

    assert "后摇" in queries
    assert "日本的后摇" in queries  # a country is a constraint, not filler


def test_an_english_request_gets_the_chinese_form_too() -> None:
    queries = catalog_queries("late night jazz")

    assert "爵士" in queries and "jazz" in queries
    assert "late night jazz" in queries


def test_a_request_without_a_known_genre_keeps_its_cleaned_wording() -> None:
    assert catalog_queries("久石让为宫崎骏电影写的配乐") == ["久石让为宫崎骏电影写的配乐"]
    assert catalog_queries("想听点周杰伦的歌") == ["周杰伦"]


def test_queries_are_never_empty_and_bounded() -> None:
    assert catalog_queries("想听点") == ["想听点"]
    assert len(catalog_queries("爵士和摇滚和后摇")) <= 5


# --- ranking ---------------------------------------------------------------------------------


def test_an_artist_found_by_more_queries_ranks_higher() -> None:
    hits = [("后摇", "惘闻"), ("post-rock", "惘闻"), ("后摇", "路人"), ("后摇", "路人")]

    scores = artist_scores(hits)

    assert scores["惘闻"] > scores["路人"]


def test_an_artist_named_in_the_web_research_ranks_higher_but_a_lone_hit_stays_listed() -> None:
    hits = [("后摇", "Mogwai"), ("后摇", "Unknown Act")]

    scores = artist_scores(hits, ["The Scottish band Mogwai defined the genre."])

    assert scores["mogwai"] > scores["unknown act"]
    assert "unknown act" in scores  # one sighting is enough to stay eligible


def test_a_name_inside_another_word_is_not_a_mention() -> None:
    scores = artist_scores([("rock", "Cat")], ["a category of music"])

    assert scores["cat"] == 3.0  # one query, one hit, no mention


# --- the pool spreads its verification across artists -----------------------------------------


def _pool_with(catalog: SidecarLikeCatalog, **kwargs):
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": catalog}, preference=("netease",))
    )
    return CatalogPoolBuilder(retrieval, PoolBuildConfig(**kwargs))


def _catalog_with_one_band_dominating() -> SidecarLikeCatalog:
    tracks = [track(f"a{i}", "Band A", f"A song {i}") for i in range(10)]
    tracks += [track(f"b{i}", "Band B", f"B song {i}") for i in range(2)]
    tracks += [track(f"c{i}", "Band C", f"C song {i}") for i in range(2)]
    return SidecarLikeCatalog(
        tracks,
        {
            "genre": [f"a{i}" for i in range(10)] + ["b0", "b1", "c0", "c1"],
        },
    )


def test_one_artist_cannot_take_the_whole_verification_budget() -> None:
    catalog = _catalog_with_one_band_dominating()

    pool = asyncio.run(
        _pool_with(catalog, max_verifications=6, search_limit=20).build(keyword_queries=["genre"])
    )

    artists = [entry.primary_artist for entry in pool.entries]
    assert set(artists) == {"Band A", "Band B", "Band C"}
    assert artists.count("Band A") <= 2


def test_the_per_artist_cap_holds_even_when_the_budget_is_large() -> None:
    catalog = _catalog_with_one_band_dominating()

    pool = asyncio.run(
        _pool_with(catalog, max_verifications=24, search_limit=20).build(keyword_queries=["genre"])
    )

    assert [entry.primary_artist for entry in pool.entries].count("Band A") == 2


def test_the_best_ranked_artist_is_verified_first() -> None:
    tracks = [track("x0", "Solo", "Lone song"), track("y0", "Twice", "T1"), track("y1", "Twice", "T2")]
    catalog = SidecarLikeCatalog(tracks, {"q1": ["x0", "y0"], "q2": ["y1"]})

    pool = asyncio.run(
        _pool_with(catalog, max_verifications=1, search_limit=20).build(keyword_queries=["q1", "q2"])
    )

    assert {entry.primary_artist for entry in pool.entries} == {"Twice"}  # found by both queries


def test_research_that_names_an_artist_lifts_it_into_the_budget() -> None:
    tracks = [track(f"n{i}", f"Aaa Noise {i}", f"Song {i}") for i in range(5)] + [
        track("g0", "Godspeed", "Real song")
    ]
    catalog = SidecarLikeCatalog(tracks, {"q": [f"n{i}" for i in range(5)] + ["g0"]})

    without = asyncio.run(
        _pool_with(catalog, max_verifications=2, search_limit=20).build(keyword_queries=["q"])
    )
    with_evidence = asyncio.run(
        _pool_with(catalog, max_verifications=2, search_limit=20).build(
            keyword_queries=["q"], evidence_texts=["Godspeed are central to the scene."]
        )
    )

    assert "Godspeed" not in {entry.primary_artist for entry in without.entries}
    assert "Godspeed" in {entry.primary_artist for entry in with_evidence.entries}


def test_a_named_artist_may_take_more_of_the_budget_than_an_ordinary_one() -> None:
    tracks = [track(f"s{i}", "椎名林檎", f"曲 {i}") for i in range(8)]
    catalog = SidecarLikeCatalog(tracks, {"椎名林檎": [f"s{i}" for i in range(8)]})

    ordinary = asyncio.run(
        _pool_with(catalog, search_limit=20).build(artist_queries=["椎名林檎"])
    )
    named = asyncio.run(
        _pool_with(catalog, search_limit=20).build(
            artist_queries=["椎名林檎"], named_artists=["椎名林檎"]
        )
    )

    assert sum(e.source is PoolSource.ARTIST_SEARCH for e in ordinary.entries) == 4
    assert sum(e.source is PoolSource.ARTIST_SEARCH for e in named.entries) == 8
    assert all(o.status is AvailabilityStatus.PLAYABLE for o in named.outcomes)


# --- a genre paired with a theme ---------------------------------------------------------------


def test_a_genre_paired_with_a_theme_searches_the_pair() -> None:
    queries = catalog_queries("想听点游戏里的爵士配乐")

    assert queries[0] == "游戏 爵士"
    assert "game jazz" in queries
    assert "爵士" in queries and "jazz" in queries


def test_a_theme_alone_is_not_a_genre_query() -> None:
    assert catalog_queries("想听点游戏音乐") == ["游戏音乐"]


# --- a cover of the opening is still a cover ----------------------------------------------------


def test_a_keyword_hit_that_repeats_a_reserved_song_is_treated_as_a_cover() -> None:
    from wavecast.catalog_pool import CatalogPool, PoolEntry
    from wavecast.providers.retrieval import VersionKind

    def entry(ref: str, artist: str, title: str, source: PoolSource) -> PoolEntry:
        return PoolEntry(
            track_ref=f"netease:{ref}",
            artist=artist,
            title=title,
            primary_artist=artist,
            duration_seconds=200,
            version_kind=VersionKind.STUDIO,
            source=source,
        )

    pool = CatalogPool(
        entries=[
            entry("1", "久石譲", "天空の城ラピュタ", PoolSource.ARTIST_SEARCH),
            entry("2", "钢琴乐队", "Summer (钢琴版)", PoolSource.KEYWORD_SEARCH),
        ],
        reserved_song_keys=["summer"],
    )

    titles = [item.title for item in pool.listing()]

    assert titles == ["天空の城ラピュタ"]
    assert "Summer (钢琴版)" in [
        item.title for item in CatalogPool(entries=pool.entries).listing()
    ]  # without the reserved key the cover would be offered
