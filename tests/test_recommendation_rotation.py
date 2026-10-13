"""Home shelf: a few ideas at a time, "换一批" rotates the stock, and generation is capped per day."""

from datetime import UTC, datetime, timedelta

from wavecast.recommendations import (
    BATCH_SIZE,
    DAILY_GENERATION_CAP,
    IDEA_RETENTION_WINDOW,
    MAX_RETAINED_IDEAS_PER_USER,
    MAX_STORED_IDEAS_PER_USER,
    SHELF_SIZE,
    InMemoryProgramIdeaRepository,
    ProgramIdeaDraft,
    ProgramIdeaStatus,
    RecommendationService,
    UserContext,
    UserContextAggregator,
    ideas_to_retain,
)
from wavecast.user_context import InMemoryUserEventRepository, InMemoryUserPreferencesRepository

from tests.test_recommendations import InMemoryProgramProposalRepository


class Planner:
    source = "stub"

    def __init__(self, per_batch: int = BATCH_SIZE) -> None:
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


def test_the_first_shelf_shows_a_shelf_and_keeps_the_rest_in_stock() -> None:
    planner, clock = Planner(), Clock()
    service, _ = _service(planner, clock)

    shelf = service.shelf_for_user("u")

    assert len(shelf.ideas) == SHELF_SIZE and shelf.has_more
    assert planner.calls == 1
    # reading the shelf again changes nothing and costs nothing
    assert _ids(service.shelf_for_user("u")) == _ids(shelf) and planner.calls == 1


def test_next_shelf_offers_the_stock_without_a_model_call_and_never_repeats() -> None:
    planner, clock = Planner(per_batch=2 * SHELF_SIZE), Clock()
    service, repository = _service(planner, clock)
    first = service.shelf_for_user("u")

    second = service.next_shelf("u", _ids(first))

    assert planner.calls == 1
    assert len(second.ideas) == SHELF_SIZE and not set(_ids(first)) & set(_ids(second))
    states = {idea.id: idea.status for idea in repository.list_for_user("u", limit=60)}
    assert all(states[idea_id] is ProgramIdeaStatus.DISMISSED for idea_id in _ids(first))


def test_a_new_batch_tops_the_shelf_up_before_the_stock_runs_dry() -> None:
    planner, clock = Planner(), Clock()
    service, _ = _service(planner, clock)
    first = service.shelf_for_user("u")
    clock.tick()

    second = service.next_shelf("u", _ids(first))

    # Four were left in stock (fewer than a shelf), so a second batch is made and shown in full.
    assert planner.calls == 2
    assert len(second.ideas) == SHELF_SIZE
    assert not set(_ids(first)) & set(_ids(second))
    assert {idea.title for idea in second.ideas} <= {f"批次2-想法{i}" for i in range(BATCH_SIZE)}
    assert "批次1-想法0" in planner.avoid_seen[1]


def test_once_the_daily_cap_is_reached_ideas_already_seen_come_round_again() -> None:
    planner, clock = Planner(per_batch=2 * SHELF_SIZE), Clock()
    service, repository = _service(planner, clock, daily_generation_cap=1)
    first = service.shelf_for_user("u")  # the only batch
    second = service.next_shelf("u", _ids(first))
    clock.tick()
    assert planner.calls == 1 and second.has_more

    third = service.next_shelf("u", _ids(second))  # nothing unseen is left, and the cap is used

    assert planner.calls == 1
    assert set(_ids(third)) == set(_ids(first))
    assert not set(_ids(third)) & set(_ids(second)) and third.has_more
    # the plain read agrees with what the listener was just shown
    assert set(_ids(service.shelf_for_user("u"))) == set(_ids(third))
    states = {idea.id: idea.status for idea in repository.list_for_user("u", limit=60)}
    assert all(states[idea_id] is ProgramIdeaStatus.AVAILABLE for idea_id in _ids(third))
    assert all(states[idea_id] is ProgramIdeaStatus.DISMISSED for idea_id in _ids(second))
    # and it keeps going round: the two shelves alternate
    assert set(_ids(service.next_shelf("u", _ids(third)))) == set(_ids(second))


def test_a_listener_with_nothing_else_to_see_keeps_the_shelf_instead_of_an_empty_one() -> None:
    planner, clock = Planner(per_batch=4), Clock()
    service, repository = _service(planner, clock, daily_generation_cap=1)
    shelf = service.shelf_for_user("u")  # four ideas: fewer than a shelf, and no cap left

    capped = service.next_shelf("u", _ids(shelf))

    assert planner.calls == 1
    assert _ids(capped) == _ids(shelf) and not capped.has_more
    states = {idea.id: idea.status for idea in repository.list_for_user("u", limit=60)}
    assert all(states[idea_id] is ProgramIdeaStatus.AVAILABLE for idea_id in _ids(shelf))


def test_ideas_the_listener_started_are_not_offered_again() -> None:
    planner, clock = Planner(per_batch=2 * SHELF_SIZE), Clock()
    service, _ = _service(planner, clock, daily_generation_cap=1)
    first = service.shelf_for_user("u")
    started = first.ideas[0]
    assert service.claim_for_materialization("u", started.id) is not None
    second = service.next_shelf("u", _ids(first))
    third = service.next_shelf("u", _ids(second))

    assert started.id not in _ids(second) and started.id not in _ids(third)


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
    assert 1 <= DAILY_GENERATION_CAP <= 12


def test_the_cap_counts_generations_even_when_they_follow_each_other_instantly() -> None:
    planner, clock = Planner(per_batch=4), Clock()
    service, _ = _service(planner, clock)
    shelf = service.shelf_for_user("u")

    # 60 presses of 换一批 at one frozen instant: each wants a new batch, only the cap says no.
    for _ in range(60):
        shelf = service.next_shelf("u", _ids(shelf))

    assert planner.calls == DAILY_GENERATION_CAP
    assert shelf.ideas  # the cap never leaves the listener with an empty shelf


def test_the_cap_still_counts_when_a_days_batches_hold_far_more_than_thirty_ideas() -> None:
    planner, clock = Planner(per_batch=BATCH_SIZE), Clock()
    service, repository = _service(planner, clock)
    shelf = service.shelf_for_user("u")

    for _ in range(80):
        clock.tick()
        shelf = service.next_shelf("u", _ids(shelf))

    stored = repository.list_for_user("u", limit=MAX_RETAINED_IDEAS_PER_USER)
    # Dropping to the newest thirty used to forget older batches, so a higher cap never bit.
    assert len(stored) > MAX_STORED_IDEAS_PER_USER
    assert planner.calls == DAILY_GENERATION_CAP


def test_retention_keeps_the_newest_thirty_and_everything_from_the_last_day() -> None:
    now = datetime(2026, 10, 12, 12, tzinfo=UTC)

    def newest_first(count: int, spacing: timedelta) -> list[tuple[str, datetime]]:
        return [(f"i{n}", now - spacing * n) for n in range(count)]

    sparse = newest_first(50, timedelta(days=1))
    assert ideas_to_retain(sparse) == {f"i{n}" for n in range(MAX_STORED_IDEAS_PER_USER)}

    busy = newest_first(120, timedelta(minutes=5))
    assert ideas_to_retain(busy) == {f"i{n}" for n in range(120)}

    flood = newest_first(300, timedelta(seconds=1))
    assert ideas_to_retain(flood) == {f"i{n}" for n in range(MAX_RETAINED_IDEAS_PER_USER)}

    edge = [("new", now), ("inside", now - IDEA_RETENTION_WINDOW)]
    old = [(f"old{n}", now - IDEA_RETENTION_WINDOW - timedelta(minutes=n + 1)) for n in range(40)]
    assert ideas_to_retain([*edge, *old]) == {"new", "inside", *(f"old{n}" for n in range(28))}
    assert ideas_to_retain([]) == set()


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

    batches = {idea.batch_id for idea in repository.list_for_user("u", limit=200)}
    assert planner.calls <= DAILY_GENERATION_CAP
    assert len(batches) == planner.calls
    assert RecommendationService._rotation_lock("u") is RecommendationService._rotation_lock("u")
