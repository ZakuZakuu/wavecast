"""Last.fm tags seed catalog discovery, and never get in its way."""

import asyncio

import httpx
from wavecast.catalog_pool import CatalogPoolBuilder, PoolBuildConfig
from wavecast.music_discovery import community_tags
from wavecast.providers.config import ProviderSettings
from wavecast.providers.lastfm import LastFmArtistHints
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService

from tests.test_catalog_pool import SidecarLikeCatalog, track

KEY = "k-test-key-not-real"

# --- which requests get a tag lookup ---------------------------------------------------------


def test_a_plain_genre_request_gets_its_english_tag() -> None:
    assert community_tags("想听点后摇") == ["post-rock"]
    assert community_tags("late night jazz") == []  # "late night" narrows the request
    assert community_tags("爵士") == ["jazz"]


def test_a_request_that_narrows_the_genre_gets_no_tag_lookup() -> None:
    assert community_tags("来点日本的后摇") == []
    assert community_tags("游戏里的爵士") == []
    assert community_tags("久石让为宫崎骏电影写的配乐") == []
    assert community_tags("想听点周杰伦的歌") == []


# --- the provider ----------------------------------------------------------------------------


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _ok(names: list[str]) -> dict[str, object]:
    return {"topartists": {"artist": [{"name": name} for name in names]}}


def test_tag_artists_are_returned_and_cached() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_ok(["Mogwai", "Slint", " "]))

    hints = LastFmArtistHints(KEY, client=_client(httpx.MockTransport(handler)))

    first = asyncio.run(hints.artists_for_tag("Post-Rock", limit=5))
    second = asyncio.run(hints.artists_for_tag("post-rock", limit=5))

    assert first == second == ["Mogwai", "Slint"]
    assert len(calls) == 1
    assert calls[0].url.params["tag"] == "post-rock"
    assert calls[0].url.params["method"] == "tag.gettopartists"


def test_every_failure_is_an_empty_list_and_the_key_is_not_logged(caplog) -> None:  # type: ignore[no-untyped-def]
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    cases = {
        "transport": boom,
        "http_error": lambda request: httpx.Response(503),
        "lastfm_error_body": lambda request: httpx.Response(200, json={"error": 6, "message": "x"}),
        "not_json": lambda request: httpx.Response(200, text="<html>"),
        "wrong_shape": lambda request: httpx.Response(200, json={"topartists": {"artist": "?"}}),
    }
    for name, handler in cases.items():
        hints = LastFmArtistHints(KEY, client=_client(httpx.MockTransport(handler)))
        assert asyncio.run(hints.artists_for_tag("jazz", limit=5)) == [], name

    assert KEY not in caplog.text


def test_failures_are_not_cached() -> None:
    answers = iter([httpx.Response(503), httpx.Response(200, json=_ok(["Mogwai"]))])
    hints = LastFmArtistHints(
        KEY, client=_client(httpx.MockTransport(lambda request: next(answers)))
    )

    assert asyncio.run(hints.artists_for_tag("post-rock", limit=3)) == []
    assert asyncio.run(hints.artists_for_tag("post-rock", limit=3)) == ["Mogwai"]


def test_without_a_key_nothing_is_requested() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call Last.fm without a key")

    hints = LastFmArtistHints(None, client=_client(httpx.MockTransport(handler)))

    assert asyncio.run(hints.artists_for_tag("jazz", limit=5)) == []
    assert LastFmArtistHints.from_settings(ProviderSettings()) is None
    assert LastFmArtistHints.from_settings(ProviderSettings(lastfm_api_key=KEY)) is not None


# --- the pool --------------------------------------------------------------------------------


class _Hints:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.asked: list[str] = []

    async def artists_for_tag(self, tag: str, *, limit: int) -> list[str]:
        self.asked.append(tag)
        return self.names[:limit]


def _builder(catalog: SidecarLikeCatalog, hints: object | None, **kwargs: int) -> CatalogPoolBuilder:
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": catalog}, preference=("netease",))
    )
    return CatalogPoolBuilder(
        retrieval, PoolBuildConfig(search_limit=20, **kwargs), hints=hints  # type: ignore[arg-type]
    )


def _catalog() -> SidecarLikeCatalog:
    tracks = [track(f"a{i}", "Band A", f"A song {i}") for i in range(6)]
    tracks += [track("m0", "Mogwai", "Hunted by a Freak"), track("m1", "Mogwai", "Auto Rock")]
    tracks += [track("s0", "Slint", "Washer"), track("x0", "Mogwai Tribute Band", "Cover song")]
    return SidecarLikeCatalog(
        tracks,
        {
            "后摇": [f"a{i}" for i in range(6)],
            "Mogwai": ["m0", "m1", "x0"],
            "Slint": ["s0"],
        },
    )


def test_hinted_artists_join_the_pool_and_share_the_spread() -> None:
    hints = _Hints(["Mogwai", "Slint"])

    pool = asyncio.run(
        _builder(_catalog(), hints, max_verifications=8).build(
            keyword_queries=["后摇"], hint_tags=["post-rock"]
        )
    )

    artists = {entry.primary_artist for entry in pool.entries}
    assert {"Mogwai", "Slint", "Band A"} <= artists
    assert [entry.primary_artist for entry in pool.entries].count("Mogwai") <= 2
    assert hints.asked == ["post-rock"]


def test_a_tribute_act_that_merely_contains_the_name_is_not_the_artist() -> None:
    pool = asyncio.run(
        _builder(_catalog(), _Hints(["Mogwai"]), max_verifications=8).build(
            keyword_queries=["后摇"], hint_tags=["post-rock"]
        )
    )

    assert "Mogwai Tribute Band" not in {entry.primary_artist for entry in pool.entries}


def test_hints_that_are_not_in_the_catalog_cost_nothing() -> None:
    pool = asyncio.run(
        _builder(_catalog(), _Hints(["Nobody At All"]), max_verifications=8).build(
            keyword_queries=["后摇"], hint_tags=["post-rock"]
        )
    )

    assert {entry.primary_artist for entry in pool.entries} == {"Band A"}


def test_no_provider_or_no_tag_is_the_same_as_before() -> None:
    plain = asyncio.run(_builder(_catalog(), None, max_verifications=8).build(keyword_queries=["后摇"]))
    unused = _Hints(["Mogwai"])
    tagless = asyncio.run(
        _builder(_catalog(), unused, max_verifications=8).build(keyword_queries=["后摇"])
    )
    with_none = asyncio.run(
        _builder(_catalog(), None, max_verifications=8).build(
            keyword_queries=["后摇"], hint_tags=["post-rock"]
        )
    )

    assert [e.track_ref for e in plain.entries] == [e.track_ref for e in tagless.entries]
    assert [e.track_ref for e in plain.entries] == [e.track_ref for e in with_none.entries]
    assert unused.asked == []


def test_a_community_tag_outranks_a_lone_catalog_hit() -> None:
    from wavecast.music_discovery import artist_scores

    scores = artist_scores(
        [("后摇", "Obscure"), ("post-rock", "Obscure"), ("tag:post-rock", "Mogwai")]
    )

    assert scores["mogwai"] > scores["obscure"]
