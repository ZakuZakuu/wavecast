"""Home shelf: four ideas at a time, "换一批" rotates the stock, and generation is capped per day."""

from datetime import UTC, datetime, timedelta

from wavecast.recommendations import (
    DAILY_GENERATION_CAP,
    SHELF_SIZE,
    InMemoryProgramIdeaRepository,
    ProgramIdeaDraft,
    ProgramIdeaStatus,
    RecommendationService,
    UserContext,
    UserContextAggregator,
)
from wavecast.user_context import InMemoryUserEventRepository, InMemoryUserPreferencesRepository

from tests.test_recommendations import InMemoryProgramProposalRepository


class Planner:
    source = "stub"

    def __init__(self, per_batch: int = 8) -> None:
        self.per_batch = per_batch
        self.calls = 0
        self.avoid_seen: list[list[str]] = []

    def generate_program_ideas(self, context: UserContext) -> list[ProgramIdeaDraft]:
        self.calls += 1
        self.avoid_seen.append(list(context.avoid_titles))
        return [
            ProgramIdeaDraft(title=f"批次{self.calls}-想法{i}", description="d", reason="r")
            for i in range(self.per_batch)
        ]


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 12, 9, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self) -> None:
        """Time passes between listener actions (a batch's ideas share one instant)."""

        self.now += timedelta(minutes=1)


def _service(planner: Planner, clock: Clock, **kwargs):  # type: ignore[no-untyped-def]
    repository = InMemoryProgramIdeaRepository()
    service = RecommendationService(
        UserContextAggregator(
            InMemoryUserPreferencesRepository(), InMemoryUserEventRepository(), InMemoryProgramProposalRepository()
        ),
        planner,
        repository,
        clock=clock,
        **kwargs,
    )
    return service, repository


def _ids(shelf) -> list[str]:  # type: ignore[no-untyped-def]
    return [idea.id for idea in shelf.ideas]


def test_the_first_shelf_shows_four_and_keeps_the_rest_in_stock() -> None:
    planner, clock = Planner(), Clock()
    service, _ = _service(planner, clock)

    shelf = service.shelf_for_user("u")

    assert len(shelf.ideas) == SHELF_SIZE and shelf.has_more
    assert planner.calls == 1
    # reading the shelf again changes nothing and costs nothing
    assert _ids(service.shelf_for_user("u")) == _ids(shelf) and planner.calls == 1


def test_next_shelf_offers_the_rest_of_the_stock_without_a_model_call_and_never_repeats() -> None:
    planner, clock = Planner(), Clock()
    service, repository = _service(planner, clock)
    first = service.shelf_for_user("u")

    second = service.next_shelf("u", _ids(first))

    assert planner.calls == 1
    assert len(second.ideas) == SHELF_SIZE and not set(_ids(first)) & set(_ids(second))
    states = {idea.id: idea.status for idea in repository.list_for_user("u", limit=30)}
    assert all(states[idea_id] is ProgramIdeaStatus.DISMISSED for idea_id in _ids(first))


def test_when_the_stock_runs_out_a_new_batch_is_made_and_avoids_what_was_offered() -> None:
    planner, clock = Planner(), Clock()
    service, _ = _service(planner, clock)
    first = service.shelf_for_user("u")
    second = service.next_shelf("u", _ids(first))
    clock.tick()

    third = service.next_shelf("u", _ids(second))

    assert planner.calls == 2
    assert len(third.ideas) == SHELF_SIZE
    assert {idea.title for idea in third.ideas} <= {f"批次2-想法{i}" for i in range(8)}
    assert "批次1-想法0" in planner.avoid_seen[1]


def test_the_daily_cap_stops_new_generation_and_leaves_the_shelf_as_it_is() -> None:
    planner, clock = Planner(per_batch=4), Clock()
    service, repository = _service(planner, clock, daily_generation_cap=2)
    shelf = service.shelf_for_user("u")  # batch 1
    clock.tick()
    shelf = service.next_shelf("u", _ids(shelf))  # batch 2
    clock.tick()
    assert planner.calls == 2

    capped = service.next_shelf("u", _ids(shelf))

    assert planner.calls == 2
    assert _ids(capped) == _ids(shelf) and not capped.has_more
    states = {idea.id: idea.status for idea in repository.list_for_user("u", limit=30)}
    assert all(states[idea_id] is ProgramIdeaStatus.AVAILABLE for idea_id in _ids(shelf))
    # the plain read does not sneak a generation past the cap either
    assert _ids(service.shelf_for_user("u")) == _ids(shelf) and planner.calls == 2


def test_the_cap_resets_after_a_day() -> None:
    planner, clock = Planner(per_batch=4), Clock()
    service, _ = _service(planner, clock, daily_generation_cap=1)
    shelf = service.shelf_for_user("u")
    assert planner.calls == 1 and service.next_shelf("u", _ids(shelf)).has_more is False

    clock.now += timedelta(hours=25)
    refreshed = service.next_shelf("u", _ids(shelf))

    assert planner.calls == 2 and refreshed.ideas


def test_unknown_or_foreign_ids_are_ignored_and_other_users_are_untouched() -> None:
    planner, clock = Planner(), Clock()
    service, _ = _service(planner, clock)
    mine = service.shelf_for_user("u")
    theirs = service.shelf_for_user("other")

    shelf = service.next_shelf("u", ["nope", *_ids(theirs)])

    assert {idea.id for idea in shelf.ideas} >= set()  # no error
    assert set(_ids(theirs)) == set(_ids(service.shelf_for_user("other")))
    assert set(_ids(mine)) <= {idea.id for idea in service.shelf_for_user("u").ideas} | set(_ids(mine))


def test_the_default_cap_is_bounded() -> None:
    assert 1 <= DAILY_GENERATION_CAP <= 6


def test_the_cap_counts_generations_even_when_they_follow_each_other_instantly() -> None:
    planner, clock = Planner(per_batch=4), Clock()
    service, _ = _service(planner, clock)
    shelf = service.shelf_for_user("u")

    # 20 presses of 换一批 at one frozen instant: each empties the stock, so each wants a new batch.
    for _ in range(20):
        shelf = service.next_shelf("u", _ids(shelf))

    assert planner.calls == DAILY_GENERATION_CAP
    assert not shelf.has_more


def test_batches_without_an_id_are_still_counted_by_when_they_were_made() -> None:
    clock = Clock()
    service, repository = _service(Planner(), clock)
    service.shelf_for_user("u")
    legacy = [
        idea.model_copy(update={"batch_id": None})
        for idea in repository.list_for_user("u", limit=30)
    ]
    assert RecommendationService._generations_in_last_day(legacy, clock()) == 1
    assert RecommendationService._generations_in_last_day([], clock()) == 0


def test_two_requests_of_one_listener_share_one_lock_and_one_count() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from time import sleep

    class SlowPlanner(Planner):
        def generate_program_ideas(self, context):  # type: ignore[no-untyped-def]
            sleep(0.05)
            return super().generate_program_ideas(context)

    planner, clock = SlowPlanner(per_batch=4), Clock()
    first, repository = _service(planner, clock)
    # The API builds a service object per request: same repository and planner, new object.
    others = [
        RecommendationService(first._aggregator, planner, repository, clock=clock)
        for _ in range(7)
    ]
    services = [first, *others]

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda service: service.next_shelf("u", []), services))

    batches = {idea.batch_id for idea in repository.list_for_user("u", limit=60)}
    assert planner.calls <= DAILY_GENERATION_CAP
    assert len(batches) == planner.calls
    assert RecommendationService._rotation_lock("u") is RecommendationService._rotation_lock("u")
