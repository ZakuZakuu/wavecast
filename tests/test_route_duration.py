"""A programme ends near its time budget, on a track, whatever the songs' lengths."""

import pytest
from wavecast.assembly import (
    LiveEpisodeAssemblyRequest,
    _fit_route_to_time_budget,
    _ResolvedChapter,
    _route_underfilled,
)
from wavecast.intelligence.models import (
    ChapterPlan,
    NarrativeRole,
    NoveltyDistance,
    ResolvedTrack,
    TrackProposal,
)
from wavecast.route_duration import (
    DEFAULT_TRACK_SECONDS,
    is_underfilled,
    last_track_to_keep,
    music_budget_seconds,
    track_seconds,
)

# --- the arithmetic ------------------------------------------------------------------------


def test_an_unknown_length_is_a_typical_songs() -> None:
    assert track_seconds(None) == DEFAULT_TRACK_SECONDS
    assert track_seconds(0) == DEFAULT_TRACK_SECONDS
    assert track_seconds(417) == 417


def test_the_music_budget_is_the_programme_less_the_hosts_share() -> None:
    assert music_budget_seconds(2100, 0.1) == 1890
    assert music_budget_seconds(2100, 0.0) == 2100
    assert music_budget_seconds(2100, 5.0) == 210  # a nonsense ratio cannot erase the music


def test_a_route_is_underfilled_below_four_fifths_of_the_budget() -> None:
    assert is_underfilled([300] * 5, 2000)  # 1500 < 1600
    assert not is_underfilled([300] * 6, 2000)  # 1800 >= 1600
    assert is_underfilled([None, None], 1890)  # two typical songs


POST_ROCK = [253, 417, 208, 497, 331, 700]  # running totals 253 670 878 1375 1706 2406


def test_the_route_ends_on_the_track_nearest_the_budget() -> None:
    assert last_track_to_keep(POST_ROCK, 1890, keep_at_least=2) == 4
    assert last_track_to_keep(POST_ROCK, 2500, keep_at_least=2) == 5
    assert last_track_to_keep(POST_ROCK, 900, keep_at_least=2) == 2  # 878, not 1375


def test_short_songs_run_longer_in_count_than_long_ones() -> None:
    pop = [200] * 14

    assert last_track_to_keep(pop, 1890, keep_at_least=2) == 8  # nine songs, 1800 s
    assert last_track_to_keep(POST_ROCK, 1890, keep_at_least=2) == 4  # five songs


def test_the_opening_and_the_locked_successor_are_never_dropped() -> None:
    assert last_track_to_keep([900, 900, 900], 300, keep_at_least=2) == 1
    assert last_track_to_keep([900, 900, 900], 300, keep_at_least=1) == 0


def test_a_catalog_with_too_little_music_keeps_everything() -> None:
    assert last_track_to_keep([200, 200, 200], 3000, keep_at_least=2) == 2


def test_a_tie_goes_to_the_shorter_programme() -> None:
    assert last_track_to_keep([100, 100, 100], 250, keep_at_least=1) == 1  # 200 and 300 tie


def test_unknown_lengths_count_as_typical_songs() -> None:
    assert last_track_to_keep([None, None, None, None], 630, keep_at_least=1) == 2


def test_an_empty_route_is_refused() -> None:
    with pytest.raises(ValueError):
        last_track_to_keep([], 1000, keep_at_least=1)


# --- the route ------------------------------------------------------------------------------


def _item(index: int, seconds: int | None, role: NarrativeRole = NarrativeRole.BRIDGE) -> _ResolvedChapter:
    track = (
        ResolvedTrack(
            track_ref=f"mock:{index}",
            canonical_artist=f"Artist {index}",
            canonical_title=f"Song {index}",
            duration_seconds=seconds,
        )
        if seconds is not None
        else None
    )
    chapter = ChapterPlan(
        index=index,
        track=(
            TrackProposal(artist=f"Artist {index}", title=f"Song {index}", confidence=0.9)
            if track
            else None
        ),
        narrative_role=role,
        reason="fixture",
        novelty_distance=NoveltyDistance.CLOSE,
        narration_goal="fixture",
    )
    return _ResolvedChapter(chapter=chapter, writer_chapter=chapter, track=track, music_index=None)


def _request(seconds: int) -> LiveEpisodeAssemblyRequest:
    return LiveEpisodeAssemblyRequest(topic="x", desired_duration_seconds=seconds, max_tracks=16, max_chapters=24)


def _durations(route: list[_ResolvedChapter]) -> list[int | None]:
    return [item.track.duration_seconds if item.track else None for item in route]


def test_the_route_is_cut_after_the_track_nearest_the_budget() -> None:
    route = [_item(i, seconds) for i, seconds in enumerate(POST_ROCK)]

    fitted = _fit_route_to_time_budget(
        route, request=_request(2100), narration_ratio=0.1, keep_at_least=2
    )

    assert _durations(fitted) == POST_ROCK[:5]


def test_the_last_kept_chapter_closes_the_route() -> None:
    route = [_item(i, seconds) for i, seconds in enumerate(POST_ROCK)]

    fitted = _fit_route_to_time_budget(
        route, request=_request(2100), narration_ratio=0.1, keep_at_least=2
    )

    assert fitted[-1].chapter.narrative_role is NarrativeRole.RESOLUTION
    assert fitted[-1].writer_chapter.narrative_role is NarrativeRole.RESOLUTION
    assert [item.chapter.narrative_role for item in fitted[:-1]] == [NarrativeRole.BRIDGE] * 4


def test_a_route_that_already_fits_is_left_exactly_as_it_is() -> None:
    route = [_item(i, seconds) for i, seconds in enumerate(POST_ROCK[:5])]

    fitted = _fit_route_to_time_budget(
        route, request=_request(2100), narration_ratio=0.1, keep_at_least=2
    )

    assert fitted == route
    assert fitted[-1].chapter.narrative_role is NarrativeRole.BRIDGE  # not renamed when not cut


def test_narrative_only_chapters_after_the_last_track_are_dropped_those_before_stay() -> None:
    route = [
        _item(0, 253),
        _item(1, 417),
        _item(2, None),  # narrative beat between songs
        _item(3, 208),
        _item(4, 497),
        _item(5, 331),
        _item(6, None),  # trailing beat after the cut
        _item(7, 700),
    ]

    fitted = _fit_route_to_time_budget(
        route, request=_request(2100), narration_ratio=0.1, keep_at_least=2
    )

    assert _durations(fitted) == [253, 417, None, 208, 497, 331]


def test_the_protected_tracks_survive_even_when_they_overshoot_the_budget() -> None:
    route = [_item(0, 1500), _item(1, 1500), _item(2, 200), _item(3, 200)]

    fitted = _fit_route_to_time_budget(
        route, request=_request(1200), narration_ratio=0.1, keep_at_least=2
    )

    assert _durations(fitted) == [1500, 1500]


def test_a_long_programme_keeps_more_than_a_short_one_from_the_same_songs() -> None:
    route = [_item(i, 240) for i in range(16)]

    short = _fit_route_to_time_budget(route, request=_request(2100), narration_ratio=0.1, keep_at_least=2)
    long = _fit_route_to_time_budget(route, request=_request(3600), narration_ratio=0.1, keep_at_least=2)

    assert len(short) < len(long)
    assert 7 <= len(short) <= 9  # about 31 minutes of music
    assert 13 <= len(long) <= 14  # about 54 minutes of music


def test_underfilled_uses_the_real_lengths_of_the_route_so_far() -> None:
    request = _request(2100)  # 1890 s of music, underfilled below 1512 s

    assert _route_underfilled(request, 0.1, [_item(i, 240) for i in range(5)])  # 1200 s
    assert not _route_underfilled(request, 0.1, [_item(i, 400) for i in range(5)])  # 2000 s
    assert not _route_underfilled(request, 0.1, [_item(0, 1600)])  # one very long song fills it


# --- through the session builder ------------------------------------------------------------


def test_a_programme_is_cut_to_its_budget_when_the_songs_are_long(tmp_path) -> None:
    import asyncio

    from wavecast.providers.fakes import MockMusicProvider

    from tests.test_episode_assembly import service

    music = MockMusicProvider()
    for ref, track in list(music._tracks.items()):
        music._tracks[ref] = track.model_copy(update={"duration_seconds": 600})
    assembly = service(tmp_path, music=music)
    opening = ResolvedTrack(
        track_ref="mock:opening",
        canonical_artist="Mira Fields",
        canonical_title="Neon First Light",
        duration_seconds=600,
    )

    short = asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="fixture", desired_duration_seconds=1200, max_tracks=6, max_chapters=10
            ),
            opening_track=opening,
        )
    )
    long = asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="fixture", desired_duration_seconds=7200, max_tracks=6, max_chapters=10
            ),
            opening_track=opening,
        )
    )

    def tracks(session) -> int:  # type: ignore[no-untyped-def]
        return sum(1 for chapter in session.chapters if chapter.resolved_track is not None)

    tiny = asyncio.run(
        assembly.prepare_progressive_session(
            LiveEpisodeAssemblyRequest(
                topic="fixture", desired_duration_seconds=300, max_tracks=6, max_chapters=10
            ),
            opening_track=opening,
        )
    )

    assert tracks(tiny) == 1  # never cut down to the opening alone
    assert tracks(short) == 1  # the opening (600 s) and one more already reach the budget
    assert tracks(long) >= 2  # a long request keeps what the catalog has
    assert short.chapters[-1].chapter.narrative_role is NarrativeRole.RESOLUTION
