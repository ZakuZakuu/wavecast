"""A request for the versions of one work is answered with that work, or with a shorter route."""

from wavecast.assembly import LiveEpisodeAssemblyRequest, _blocked_by_spread, _confirm_work
from wavecast.intelligence.models import ResolvedTrack
from wavecast.route_work import is_version_of, requested_work
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
