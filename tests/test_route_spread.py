"""A programme that is not about particular artists does not become one artist's showcase."""

import asyncio

from wavecast.assembly import LiveEpisodeAssemblyRequest
from wavecast.catalog_pool import (
    CatalogPool,
    CatalogPoolBuilder,
    PoolBuildConfig,
    PoolEntry,
    PoolSource,
)
from wavecast.intelligence.models import (
    ChapterPlan,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    ResolvedTrack,
    TrackProposal,
)
from wavecast.providers.contracts import TrackMetadata
from wavecast.providers.fakes import MockMusicProvider
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService, VersionKind
from wavecast.route_spread import (
    ARTIST_ROUTE_CAP,
    artist_plays,
    at_artist_cap,
    same_artist,
    same_song_other_artist,
    spread_cap,
)
from wavecast.stations import StationId

from tests.test_catalog_pool import SidecarLikeCatalog, track
from tests.test_episode_assembly import RecordingAssemblyLLM, service


def rt(artist: str, title: str, ref: str | None = None) -> ResolvedTrack:
    return ResolvedTrack(
        track_ref=ref or f"mock:{artist}:{title}", canonical_artist=artist, canonical_title=title
    )


# --- who is limited ---------------------------------------------------------------------------


def test_a_generic_programme_is_limited_and_a_named_or_portrait_one_is_not() -> None:
    assert spread_cap(required_artists=[], station=None) == ARTIST_ROUTE_CAP == 2
    assert spread_cap(required_artists=[], station=StationId.CASUAL) == 2
    assert spread_cap(required_artists=[], station=StationId.LINEAGE) == 2
    assert spread_cap(required_artists=["椎名林檎"], station=None) is None
    assert spread_cap(required_artists=[], station=StationId.PORTRAIT) is None


# --- counting an artist ------------------------------------------------------------------------


def test_the_same_lead_artist_counts_across_credits_and_trio_names() -> None:
    assert same_artist("Bill Evans", "Bill Evans Trio")
    assert same_artist("Sade", "SADE")
    assert same_artist("Miles Davis, John Coltrane", "Miles Davis")
    assert not same_artist("Bill Evans", "Gil Evans")
    assert not same_artist("", "Sade")


def test_the_cap_counts_the_opening_track_too() -> None:
    used = [rt("Mogwai", "Auto Rock"), rt("Slint", "Washer"), rt("Mogwai", "Hunted")]

    assert artist_plays("Mogwai", used) == 2
    assert at_artist_cap("Mogwai", used, 2)
    assert not at_artist_cap("Slint", used, 2)
    assert not at_artist_cap("Mogwai", used, None)


def test_a_long_title_under_two_artists_is_one_song_but_a_short_one_is_not() -> None:
    assert same_song_other_artist(
        rt("Bill Evans", "My Funny Valentine"), rt("Chet Baker", "My Funny Valentine (Remastered)")
    )
    assert not same_song_other_artist(rt("A", "Home"), rt("B", "Home"))
    assert not same_song_other_artist(
        rt("Bill Evans", "My Funny Valentine"), rt("Bill Evans Trio", "My Funny Valentine")
    )


# --- what the Curator is shown -----------------------------------------------------------------


def _entry(ref: str, artist: str, title: str, source: PoolSource) -> PoolEntry:
    return PoolEntry(
        track_ref=f"netease:{ref}",
        artist=artist,
        title=title,
        primary_artist=artist,
        duration_seconds=200,
        version_kind=VersionKind.UNKNOWN,
        source=source,
    )


def test_a_spread_listing_shows_one_song_per_artist_before_a_second_of_any() -> None:
    entries = [
        *[_entry(f"o{i}", "Opener", f"Opener {i}", PoolSource.ARTIST_SEARCH) for i in range(4)],
        _entry("a", "Alpha", "Alpha 0", PoolSource.KEYWORD_SEARCH),
        _entry("b", "Beta", "Beta 0", PoolSource.KEYWORD_SEARCH),
        _entry("a1", "Alpha", "Alpha 1", PoolSource.KEYWORD_SEARCH),
    ]

    plain = CatalogPool(entries=entries, named_artists=[]).listing(max_per_artist=3)
    spread = CatalogPool(entries=entries, named_artists=[], spread_artists=True).listing(
        max_per_artist=3
    )

    assert [item.primary_artist for item in plain[:3]] == ["Opener"] * 3
    assert [item.primary_artist for item in spread[:3]] == ["Opener", "Alpha", "Beta"]
    assert len(spread) == len(plain)  # nothing is dropped, only reordered


# --- covers are not offered as the artist's songs ---------------------------------------------


def _pool(tracks, results, **kwargs):
    catalog = SidecarLikeCatalog(tracks, results)
    retrieval = MusicRetrievalService(
        MusicProviderRegistry({"netease": catalog}, preference=("netease",))
    )
    return CatalogPoolBuilder(retrieval, PoolBuildConfig(search_limit=20)).build(**kwargs)


def test_a_track_that_says_it_is_a_cover_is_not_offered_for_a_search_on_the_artist() -> None:
    tracks = [
        track("1", "久石让", "Summer"),
        track("2", "路人甲", "Summer (翻自 久石让)"),
        track("3", "路人乙", "One Summer Day (Cover)"),
        track("4", "久石让", "Cover Me"),  # a title that merely contains the word
    ]
    pool = asyncio.run(
        _pool(tracks, {"久石让": ["1", "2", "3", "4"]}, keyword_queries=["久石让"])
    )

    titles = {entry.title for entry in pool.entries}
    assert "Summer" in titles and "Cover Me" in titles
    assert "Summer (翻自 久石让)" not in titles
    assert "One Summer Day (Cover)" not in titles


def test_covers_are_kept_when_the_request_asks_for_them() -> None:
    tracks = [track("1", "路人甲", "Summer (翻自 久石让)")]

    pool = asyncio.run(
        _pool(tracks, {"翻唱 久石让": ["1"]}, keyword_queries=["翻唱 久石让"])
    )

    assert [entry.title for entry in pool.entries] == ["Summer (翻自 久石让)"]


# --- the route ---------------------------------------------------------------------------------


class _OneArtistLLM(RecordingAssemblyLLM):
    """A Curator that puts four songs by one artist into the route."""

    async def structured(self, prompt, output_type, **kwargs):  # type: ignore[no-untyped-def]
        if output_type is ProgramSkeleton:
            titles = ["Midnight Transfer", "Sg One", "Sg Two", "Sg Three"]
            return ProgramSkeleton(
                thesis="fixture",
                chapters=[
                    ChapterPlan(
                        index=i,
                        track=TrackProposal(artist="Signal Garden", title=title, confidence=0.9),
                        narrative_role=NarrativeRole.BRIDGE,
                        reason="fixture",
                        novelty_distance=NoveltyDistance.CLOSE,
                        narration_goal="fixture",
                    )
                    for i, title in enumerate(titles)
                ],
                estimated_duration_seconds=20 * 60,
            )
        return await super().structured(prompt, output_type, **kwargs)


def _music() -> MockMusicProvider:
    music = MockMusicProvider()
    extra = [
        ("sg1", "Sg One", "Signal Garden"),
        ("sg2", "Sg Two", "Signal Garden"),
        ("sg3", "Sg Three", "Signal Garden"),
        ("oa", "Oa One", "Other A"),
        ("ob", "Ob One", "Other B"),
    ]
    for ref, title, artist in extra:
        music._tracks[f"mock:{ref}"] = TrackMetadata(
            track_ref=f"mock:{ref}", title=title, artist=artist, duration_seconds=200, playable=True
        )
    for ref, item in list(music._tracks.items()):
        music._tracks[ref] = item.model_copy(update={"duration_seconds": 200})
    return music


class _StubPoolBuilder(CatalogPoolBuilder):
    async def build(self, **_kwargs):  # type: ignore[no-untyped-def,override]
        def e(ref: str, artist: str, title: str) -> PoolEntry:
            return PoolEntry(
                track_ref=f"mock:{ref}",
                artist=artist,
                title=title,
                primary_artist=artist,
                duration_seconds=200,
                version_kind=VersionKind.UNKNOWN,
                source=PoolSource.KEYWORD_SEARCH,
            )

        return CatalogPool(
            entries=[
                e("sg1", "Signal Garden", "Sg One"),
                e("sg2", "Signal Garden", "Sg Two"),
                e("sg3", "Signal Garden", "Sg Three"),
                e("oa", "Other A", "Oa One"),
                e("ob", "Other B", "Ob One"),
            ]
        )


OPENING = ResolvedTrack(
    track_ref="mock:opening",
    canonical_artist="Mira Fields",
    canonical_title="Neon First Light",
    duration_seconds=200,
)


def _session(tmp_path, **request_kwargs):  # type: ignore[no-untyped-def]
    music = _music()
    assembly = service(tmp_path, _OneArtistLLM(), music=music)
    assembly.catalog_pool_builder = _StubPoolBuilder(assembly.retrieval)
    request = LiveEpisodeAssemblyRequest(
        topic="fixture",
        desired_duration_seconds=1200,
        max_tracks=6,
        max_chapters=10,
        **request_kwargs,
    )
    return asyncio.run(assembly.prepare_progressive_session(request, opening_track=OPENING))


def _artists(session) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        chapter.resolved_track.canonical_artist
        for chapter in session.chapters
        if chapter.resolved_track is not None
    ]


def test_a_curator_route_of_one_artist_is_held_to_two_plays_and_filled_by_others(tmp_path) -> None:
    session = _session(tmp_path)

    artists = [OPENING.canonical_artist, *_artists(session)]
    assert artists.count("Signal Garden") <= 2
    assert {"Other A", "Other B"} & set(artists)


def test_a_named_artist_programme_is_not_limited(tmp_path) -> None:
    session = _session(tmp_path, required_artists=["Signal Garden"])

    assert _artists(session).count("Signal Garden") >= 3


def test_every_credited_artist_counts_toward_the_limit() -> None:
    used = [rt("Miles Davis", "So What"), rt("Kosma, Joseph, Miles Davis", "Autumn Leaves")]

    assert artist_plays("Miles Davis", used) == 2
    assert at_artist_cap("Miles Davis", used, 2)
    assert at_artist_cap("Miles Davis, John Coltrane", used, 2)  # a collaboration of a used-up artist
    assert artist_plays("Kosma, Joseph, Miles Davis", used) == 2
    assert not at_artist_cap("Bill Evans", used, 2)


def test_the_locked_second_track_counts_toward_the_limit_even_as_a_version_of_the_opening(
    tmp_path,
) -> None:
    """The second track is fixed before assembly.  Here it is the opening song under another
    artist, so its own slot is refused as a duplicate, yet it still plays and still counts."""

    music = _music()
    music._tracks["mock:cover"] = TrackMetadata(
        track_ref="mock:cover",
        title="Neon First Light",
        artist="Signal Garden",
        duration_seconds=200,
        playable=True,
    )
    assembly = service(tmp_path, _OneArtistLLM(), music=music)
    assembly.catalog_pool_builder = _StubPoolBuilder(assembly.retrieval)
    successor = ResolvedTrack(
        track_ref="mock:cover",
        canonical_artist="Signal Garden",
        canonical_title="Neon First Light",
        duration_seconds=200,
    )
    request = LiveEpisodeAssemblyRequest(
        topic="fixture", desired_duration_seconds=1200, max_tracks=6, max_chapters=10
    )

    session = asyncio.run(
        assembly.prepare_progressive_session(
            request, opening_track=OPENING, locked_successor=successor
        )
    )

    artists = [OPENING.canonical_artist, *_artists(session)]
    assert artists.count("Signal Garden") <= 2, artists
