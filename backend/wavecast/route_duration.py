"""Fitting a programme's route to its time budget.

A programme is promised by tier ("short", "long"), not by number of songs, and songs are
anywhere from three to seventeen minutes.  Counting tracks therefore gives a 13-minute
programme for one request and a 70-minute one for the next.  These helpers work with the
lengths the catalog reported, so the route ends where the budget does and still ends on a
track (the closing is written for whatever track is last).

The aim is "about right", not exact: the listener is told "about 35 minutes", never a number
of seconds.
"""

from __future__ import annotations

from collections.abc import Sequence

# Typical length of a song when the catalog did not report one.
DEFAULT_TRACK_SECONDS = 210
# A route shorter than this share of the music budget is worth extending.
UNDERFILLED_BELOW = 0.8


def track_seconds(seconds: int | None) -> int:
    """A track's length, or a typical song's when it is unknown."""

    return seconds if seconds and seconds > 0 else DEFAULT_TRACK_SECONDS


def music_budget_seconds(desired_seconds: int, narration_ratio: float) -> int:
    """The share of the programme that is music."""

    return round(desired_seconds * (1.0 - max(0.0, min(0.9, narration_ratio))))


def is_underfilled(lengths: Sequence[int | None], budget_seconds: int) -> bool:
    """True when the route is clearly shorter than its budget."""

    return sum(track_seconds(item) for item in lengths) < budget_seconds * UNDERFILLED_BELOW


def last_track_to_keep(
    lengths: Sequence[int | None], budget_seconds: int, *, keep_at_least: int
) -> int:
    """Index (into ``lengths``) of the last track to keep.

    The first ``keep_at_least`` tracks are never dropped (the opening and the track already
    locked behind it).  After those, the route ends on the track whose running total lands
    closest to the budget; a tie goes to the shorter programme.
    """

    if not lengths:
        raise ValueError("a route needs at least one track")
    floor = max(0, min(len(lengths), keep_at_least) - 1)
    total = 0
    best_index = floor
    best_gap: int | None = None
    for index, item in enumerate(lengths):
        total += track_seconds(item)
        if index < floor:
            continue
        gap = abs(total - budget_seconds)
        if best_gap is None or gap < best_gap:
            best_index, best_gap = index, gap
    return best_index
