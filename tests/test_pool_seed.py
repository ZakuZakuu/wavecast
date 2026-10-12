"""A programme's variety seed changes which songs the pool verifies, not just their order."""

import asyncio

from wavecast.catalog_pool import CatalogPoolBuilder, PoolBuildConfig
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService

from tests.test_catalog_pool import SidecarLikeCatalog, track


def _catalog() -> SidecarLikeCatalog:
    tracks = [
        track(f"{band}{i}", f"Band {band}", f"{band} song {i}")
        for band in "ABCDEFGH"
        for i in range(4)
    ]
    results = {"genre": [f"{band}{i}" for i in range(4) for band in "ABCDEFGH"]}
    return SidecarLikeCatalog(tracks, results)


def _build(seed: str = "", queries: tuple[str, ...] = ("genre",), **config: int) -> set[str]:
    catalog = _catalog()
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": catalog}, preference=("netease",))
    )
    builder = CatalogPoolBuilder(retrieval, PoolBuildConfig(search_limit=40, **config))
    pool = asyncio.run(builder.build(keyword_queries=list(queries), seed=seed))
    return {entry.title for entry in pool.entries}


def test_different_seeds_verify_different_songs() -> None:
    pools = {frozenset(_build(f"episode-{n}", max_verifications=8)) for n in range(12)}

    assert len(pools) >= 4


def test_the_same_seed_gives_the_same_pool() -> None:
    assert _build("episode-7", max_verifications=8) == _build("episode-7", max_verifications=8)


def test_without_a_seed_the_ranked_order_is_unchanged() -> None:
    assert _build("", max_verifications=8) == _build("", max_verifications=8)
    # The first song of the first eight artists, as the ranking alone picks them.
    assert _build("", max_verifications=4) == {"A song 0", "B song 0", "C song 0", "D song 0"}


def test_a_seed_never_drops_the_per_artist_limit_or_the_budget() -> None:
    for n in range(10):
        titles = _build(f"episode-{n}", max_verifications=8)
        assert len(titles) <= 8
        per_artist = [sum(t.startswith(f"{band} ") for t in titles) for band in "ABCDEFGH"]
        assert max(per_artist) <= 2


def test_a_clearly_better_supported_artist_is_in_every_pool() -> None:
    # Band H is found by four queries, the others by one: far more than the seed can blur.
    catalog = _catalog()
    catalog.results = {
        "q1": [f"{band}{i}" for i in range(4) for band in "ABCDEFGH"],
        "q2": ["H0", "H1"],
        "q3": ["H0", "H1"],
        "q4": ["H0", "H1"],
    }
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": catalog}, preference=("netease",))
    )
    builder = CatalogPoolBuilder(retrieval, PoolBuildConfig(search_limit=40, max_verifications=2))

    for n in range(12):
        pool = asyncio.run(
            builder.build(keyword_queries=["q1", "q2", "q3", "q4"], seed=f"episode-{n}")
        )
        assert any(entry.title.startswith("H ") for entry in pool.entries), n
