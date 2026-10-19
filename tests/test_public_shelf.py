from datetime import UTC, datetime, timedelta

from wavecast.models.episode import CoverParams
from wavecast.public_shelf import (
    BATCH_SIZE,
    FRESHNESS_WEIGHT,
    MAX_PER_AUTHOR,
    MIN_ON_SHELF,
    WINDOW_DAYS,
    PublicShelf,
    rank,
    score,
)
from wavecast.publishing import (
    ProgrammeSnapshot,
    Publication,
    PublicationStatus,
    Visibility,
    new_publication_id,
    short_code,
)
from wavecast.storage import InMemoryPublicationRepository

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def publication(
    owner: str = "author-a", *, age_days: float = 10, visibility=Visibility.PUBLIC,
    status=PublicationStatus.PUBLISHED, title: str = "节目",
) -> Publication:
    identifier = new_publication_id()
    born = NOW - timedelta(days=age_days)
    return Publication(
        id=identifier, code=short_code(identifier), source_episode_id=f"episode-{identifier}",
        owner_listener_id=owner, status=status, visibility=visibility, published_at=born,
        created_at=born, updated_at=born,
        programme=ProgrammeSnapshot(
            title=title, description="d", estimated_duration_seconds=1800, opening_track_title="s",
            opening_track_artist="a", cover=CoverParams(family="f", seed=1, palette=("#000000", "#ffffff")),
        ),
    )


def hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def test_recent_listens_count_more_than_old_ones_and_old_ones_not_at_all() -> None:
    item = publication(age_days=30)
    recent = score(item, [hours_ago(1)], NOW)
    older = score(item, [hours_ago(72)], NOW)
    outside = score(item, [NOW - timedelta(days=WINDOW_DAYS + 1)], NOW)
    assert recent > older > outside
    # Two listens a day ago are worth more than one right now.
    assert score(item, [hours_ago(24), hours_ago(24)], NOW) > score(item, [hours_ago(0)], NOW)
    assert outside == score(item, [], NOW)


def test_a_new_programme_nobody_heard_yet_can_still_be_found_but_a_heard_one_ranks_above() -> None:
    fresh = publication("author-fresh", age_days=0)
    old = publication("author-old", age_days=20)
    heard_old = publication("author-heard", age_days=20)
    ranked = rank([old, fresh, heard_old], {heard_old.id: [hours_ago(2)]}, NOW)
    assert [item.id for item in ranked] == [heard_old.id, fresh.id, old.id]
    assert score(fresh, [], NOW) == FRESHNESS_WEIGHT


def test_one_author_does_not_fill_the_shelf() -> None:
    mine = [publication("same-author", age_days=index) for index in range(5)]
    other = publication("someone-else", age_days=9)
    ranked = rank([*mine, other], {}, NOW)
    assert sum(1 for item in ranked if item.owner_listener_id == "same-author") == MAX_PER_AUTHOR
    assert other.id in {item.id for item in ranked}
    # An account and its earlier guest identity are one author.
    a = publication("guest-1")
    b = a.model_copy(update={"id": "pub-" + "b" * 32, "source_episode_id": "e2", "owner_user_id": "user-1"})
    c = a.model_copy(update={"id": "pub-" + "c" * 32, "source_episode_id": "e3", "owner_user_id": "user-1"})
    d = a.model_copy(update={"id": "pub-" + "d" * 32, "source_episode_id": "e4", "owner_user_id": "user-1"})
    assert len(rank([b, c, d], {}, NOW)) == MAX_PER_AUTHOR


class Rig:
    def __init__(self, *, cache_seconds: float = 180) -> None:
        self.clock = NOW
        self.repository = InMemoryPublicationRepository()
        self.taken_down: set[str] = set()
        self.shelf = PublicShelf(
            self.repository, now=lambda: self.clock, taken_down=lambda item: item in self.taken_down,
            cache_seconds=cache_seconds,
        )

    def add(self, **kwargs) -> Publication:
        return self.repository.create(publication(**kwargs))

    def page(self, *, mine=(), holds=(), shown=(), limit=BATCH_SIZE):
        return self.shelf.page(
            is_mine=lambda item: item.owner_listener_id in mine,
            holds_copy=lambda item: item.id in holds,
            shown=shown, limit=limit,
        )


def test_only_public_published_programmes_are_on_the_shelf() -> None:
    rig = Rig()
    shown = [rig.add(owner=f"author-{index}") for index in range(3)]
    rig.add(owner="private", visibility=Visibility.LINK)
    rig.add(owner="revoked", status=PublicationStatus.REVOKED)
    rig.add(owner="failed", status=PublicationStatus.FAILED)
    page = rig.page()
    assert {item.id for item in page.items} == {item.id for item in shown}
    assert page.hidden is False and page.has_more is False


def test_fewer_than_three_programmes_leave_the_whole_section_out() -> None:
    rig = Rig()
    for index in range(MIN_ON_SHELF - 1):
        rig.add(owner=f"author-{index}")
    assert rig.page().hidden is True
    rig.add(owner="author-new")
    rig.shelf.invalidate()
    assert rig.page().hidden is False


def test_a_listener_is_not_offered_their_own_programmes_or_ones_they_already_hold() -> None:
    rig = Rig()
    items = [rig.add(owner=f"author-{index}") for index in range(5)]
    page = rig.page(mine={"author-0"}, holds={items[1].id})
    assert {item.id for item in page.items} == {items[2].id, items[3].id, items[4].id}


def test_a_batch_is_six_and_asking_again_with_what_was_shown_gives_the_rest() -> None:
    rig = Rig()
    items = [rig.add(owner=f"author-{index}", age_days=index) for index in range(9)]
    first = rig.page()
    assert len(first.items) == BATCH_SIZE and first.has_more is True
    second = rig.page(shown=[item.id for item in first.items])
    assert {item.id for item in second.items} == {item.id for item in items} - {item.id for item in first.items}
    assert second.has_more is False and second.hidden is False
    third = rig.page(shown=[item.id for item in items])
    assert third.items == [] and third.has_more is False and third.hidden is False


def test_what_is_ranked_is_reused_for_a_few_minutes_until_something_changes() -> None:
    rig = Rig()
    for index in range(3):
        rig.add(owner=f"author-{index}")
    assert len(rig.page().items) == 3
    late = rig.add(owner="author-late")
    assert len(rig.page().items) == 3  # still the ranking from a moment ago
    rig.shelf.invalidate()
    assert len(rig.page().items) == 4
    rig.add(owner="author-later")
    rig.clock += timedelta(seconds=181)
    assert late.id in {item.id for item in rig.page().items} and len(rig.page().items) == 5


def test_a_programme_switched_off_by_hand_leaves_at_once() -> None:
    rig = Rig()
    items = [rig.add(owner=f"author-{index}") for index in range(4)]
    rig.taken_down.add(items[0].id)
    assert items[0].id not in {item.id for item in rig.page().items}


def test_the_week_of_listens_decides_the_order() -> None:
    rig = Rig()
    quiet = rig.add(owner="author-quiet", age_days=1)
    loved = rig.add(owner="author-loved", age_days=5)
    other = rig.add(owner="author-other", age_days=3)
    for number in range(4):
        rig.repository.record_listen(loved.id, f"user:{number}", at=hours_ago(3))
    page = rig.page()
    assert [item.id for item in page.items][0] == loved.id
    assert {quiet.id, other.id} <= {item.id for item in page.items}
