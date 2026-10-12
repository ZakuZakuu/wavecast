"""A request for the versions of one work is answered with that work, or with a shorter route."""

import asyncio

from wavecast.assembly import LiveEpisodeAssemblyRequest, _blocked_by_spread, _confirm_work
from wavecast.intelligence.models import ResolvedTrack
from wavecast.route_work import (
    is_version_of,
    names_work,
    requested_scope,
    requested_work,
    scope_works,
)
from wavecast.stations import StationId


def _track(artist: str, title: str, ref: str = "n:1") -> ResolvedTrack:
    return ResolvedTrack(track_ref=ref, canonical_artist=artist, canonical_title=title)


def test_only_a_request_for_the_versions_of_a_named_work_is_a_work_request() -> None:
    assert requested_work("Autumn Leaves 的不同演奏版本") == "Autumn Leaves"
    assert requested_work("《Take Five》的各种版本") == "Take Five"
    assert requested_work("比较 Summer 的版本") == "Summer"
    assert requested_work("versions of Autumn Leaves") == "Autumn Leaves"
    for other in ("想听点爵士", "久石让的现场版本", "想听点黑胶版本的爵士", "久石让为宫崎骏电影写的配乐"):
        assert requested_work(other) is None


def test_a_version_is_the_same_title_without_edition_labels() -> None:
    for title in ("Autumn Leaves", "Autumn Leaves (Live)", "Autumn Leaves - Remastered 2007", "autumn leaves"):
        assert is_version_of(title, "Autumn Leaves"), title
    # a title that only contains the words is another song
    for title in (
        "Autumn Leaves Goodnight - Seasons Songs for Kids",
        "the-cafe-beneath-the-autumn-leaves",
        "Almost Blue",
    ):
        assert not is_version_of(title, "Autumn Leaves"), title


def test_the_route_guard_refuses_other_songs_for_a_work_request() -> None:
    used = [_track("Bill Evans", "Autumn Leaves")]

    kept = _blocked_by_spread(_track("Chet Baker", "Autumn Leaves", "n:2"), used, 2, StationId.LINEAGE, "Autumn Leaves")
    other = _blocked_by_spread(_track("Bill Evans", "Alice in Wonderland", "n:3"), used, 2, StationId.LINEAGE, "Autumn Leaves")
    unrelated_request = _blocked_by_spread(_track("Bill Evans", "Alice in Wonderland", "n:3"), used, 2, StationId.LINEAGE, None)

    assert kept is False and other is True and unrelated_request is False


def test_the_work_is_read_from_the_request_and_confirmed_by_the_opening_track() -> None:
    request = LiveEpisodeAssemblyRequest(topic="Autumn Leaves 的不同演奏版本")
    assert request.required_work == "Autumn Leaves"

    confirmed = _confirm_work(request, _track("Bill Evans", "Autumn Leaves (Live)"))
    assert confirmed.required_work == "Autumn Leaves" and confirmed.work_checked

    # "邓丽君的不同版本" reads like a work request but the opening track is not a song of that name
    mistaken = _confirm_work(
        LiveEpisodeAssemblyRequest(topic="邓丽君的不同版本"), _track("邓丽君", "月亮代表我的心")
    )
    assert mistaken.required_work is None and mistaken.work_checked
    assert LiveEpisodeAssemblyRequest(topic="想听点爵士").required_work is None


# --- "music written for X's films": the same performer is not enough ----------------------------

HISAISHI_PAGE = (
    "久石让的电影配乐主要是与宫崎骏和北野武两位导演，电影例如《天空之城》、《龙猫》、《千与千寻》、"
    "《菊次郎的夏天》等。《菊次郎的夏天》中的音乐《Summer》就是如此。"
)


def test_a_request_for_one_creators_films_names_that_creator() -> None:
    assert requested_scope("久石让为宫崎骏电影写的配乐") == "宫崎骏"
    assert requested_scope("宫崎骏电影的配乐") == "宫崎骏"
    assert requested_scope("music for Miyazaki's films") == "Miyazaki"
    for other in ("久石让与宫崎骏", "久石让", "为电影写的配乐", "Autumn Leaves 的不同演奏版本", "后摇入门"):
        assert requested_scope(other) is None, other
    request = LiveEpisodeAssemblyRequest(topic="久石让为宫崎骏电影写的配乐")
    assert request.required_scope == "宫崎骏" and request.required_work is None
    assert LiveEpisodeAssemblyRequest(topic="Autumn Leaves 的不同演奏版本").required_scope is None


def test_a_track_counts_only_when_its_own_metadata_names_a_work_the_research_ties_to_the_creator() -> None:
    works = scope_works("宫崎骏", [HISAISHI_PAGE])
    assert works == ["天空之城", "龙猫", "千与千寻", "菊次郎的夏天"]
    assert names_work("天空の城ラピュタ サウンドトラック ―飛行石の謎―", works)  # の / 之 and edition words ignored
    assert not names_work("Summer", works)  # the title alone says nothing
    assert not names_work("", works)
    assert scope_works("宫崎骏", ["北野武的《花火》"]) == []  # a work next to somebody else


def test_fast_successor_is_not_taken_when_the_data_cannot_tie_it_to_the_requested_creator(
    tmp_path, monkeypatch
) -> None:
    from tests.test_episode_assembly import service

    monkeypatch.chdir(tmp_path)
    opening = _track("Mira Fields", "Neon First Light", "mock:opening")

    def bootstrap(topic: str):  # type: ignore[no-untyped-def]
        return asyncio.run(
            service(tmp_path).prepare_fast_successor(
                LiveEpisodeAssemblyRequest(topic=topic, anchor_tracks=["Neon First Light"]),
                opening_track=opening,
            )
        )

    assert bootstrap("night textures") is not None
    # The successor FastStart proposes has no album and no title that names a work of that creator.
    assert bootstrap("Mira Fields为宫崎骏电影写的配乐") is None
