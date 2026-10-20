"""「大家都在听」: the published programmes people chose to make public, ranked for the home page.

Whole programmes, played as they are (see ADR 0037). Nothing is generated for a listener who opens
one, so nothing here is limited by a daily allowance.

Ranking: how many listeners first played it in the last week, the recent ones counting more, plus a
small share for how new the programme is, so a programme nobody has heard yet can still be found.
Nobody's own programme is counted for them, and one author does not fill the shelf.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timedelta

from wavecast.publishing import Publication, utc_now
from wavecast.storage.publications import PublicationRepository

#: A listen counts for half as much every this many days.
HALF_LIFE_DAYS = 2.0
#: Listens older than this are not counted.
WINDOW_DAYS = 7
#: How much being new is worth, against one listen right now.
FRESHNESS_WEIGHT = 0.5
#: One author may have this many programmes on the shelf.
MAX_PER_AUTHOR = 10
#: Below this many programmes to show, the whole section is left out.
MIN_ON_SHELF = 1
#: Programmes shown at a time.
BATCH_SIZE = 6
#: How many ranked programmes are kept, to page through.
POOL_SIZE = 60
#: How long a ranking is reused.
CACHE_SECONDS = 180


def _decay(age: timedelta) -> float:
    return float(0.5 ** (max(0.0, age.total_seconds()) / 86400 / HALF_LIFE_DAYS))


def author_key(publication: Publication) -> str:
    return publication.owner_user_id or publication.owner_listener_id


def score(publication: Publication, listens: Collection[datetime], now: datetime) -> float:
    window_start = now - timedelta(days=WINDOW_DAYS)
    heard = sum(_decay(now - at) for at in listens if at >= window_start)
    born = publication.published_at or publication.created_at
    return heard + FRESHNESS_WEIGHT * _decay(now - born)


def rank(
    publications: Collection[Publication],
    listens: dict[str, list[datetime]],
    now: datetime,
) -> list[Publication]:
    """Best first, with no author on more than MAX_PER_AUTHOR places."""

    ordered = sorted(
        publications,
        key=lambda item: (
            score(item, listens.get(item.id, ()), now),
            item.published_at or item.created_at,
        ),
        reverse=True,
    )
    taken: dict[str, int] = {}
    ranked: list[Publication] = []
    for item in ordered:
        author = author_key(item)
        if taken.get(author, 0) >= MAX_PER_AUTHOR:
            continue
        taken[author] = taken.get(author, 0) + 1
        ranked.append(item)
        if len(ranked) >= POOL_SIZE:
            break
    return ranked


@dataclass(frozen=True)
class ShelfPage:
    items: list[Publication]
    #: More programmes could be offered by asking again with these ones as `shown`.
    has_more: bool
    #: Too few to make a shelf: show nothing at all (only said for a first page).
    hidden: bool


class PublicShelf:
    def __init__(
        self,
        repository: PublicationRepository,
        *,
        now: Callable[[], datetime] = utc_now,
        taken_down: Callable[[str], bool] = lambda _id: False,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._repository = repository
        self._now = now
        self._taken_down = taken_down
        self._cache_seconds = cache_seconds
        self._cached: tuple[datetime, list[Publication]] | None = None
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        """Something was published, withdrawn or changed: the next look ranks again."""

        with self._lock:
            self._cached = None

    def pool(self) -> list[Publication]:
        now = self._now()
        with self._lock:
            if self._cached is not None and (now - self._cached[0]).total_seconds() < self._cache_seconds:
                return self._cached[1]
        public = self._repository.list_public(POOL_SIZE * 3)
        listens = self._repository.listens_since(
            [item.id for item in public], now - timedelta(days=WINDOW_DAYS),
        )
        ranked = rank(public, listens, now)
        with self._lock:
            self._cached = (now, ranked)
        return ranked

    def page(
        self,
        *,
        is_mine: Callable[[Publication], bool],
        holds_copy: Callable[[Publication], bool],
        shown: Collection[str] = (),
        limit: int = BATCH_SIZE,
    ) -> ShelfPage:
        """The next programmes for one listener: not their own, not ones they already hold, not shown."""

        seen = set(shown)
        items: list[Publication] = []
        has_more = False
        for candidate in self.pool():
            if candidate.id in seen or self._taken_down(candidate.id) or is_mine(candidate):
                continue
            if holds_copy(candidate):
                continue
            if len(items) < limit:
                items.append(candidate)
            else:
                has_more = True
                break
        return ShelfPage(items=items, has_more=has_more, hidden=not seen and len(items) < MIN_ON_SHELF)
