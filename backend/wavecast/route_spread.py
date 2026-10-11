"""Keeping a generic programme from becoming one artist's showcase.

A request that does not name an artist ("想听点爵士") should wander across several artists, but
the pipeline had three places where the opening artist kept winning: the candidate list put
the opener's tier first, the Curator's "prefer distinct artists" was only a prompt, and every
fallback that extends a short route reused artists already on it.  The limit lives here, in
ordinary code, so no model output and no fallback can exceed it:

* a programme that names artists, or is a portrait of one, is not limited;
* any other programme plays an artist at most ``ARTIST_ROUTE_CAP`` times, the opening track
  included;
* when the catalog has no other artist left to offer, the limit gives way (a short programme
  is better than none), and the caller says so in the trace.
"""

from __future__ import annotations

from collections.abc import Iterable

from wavecast.catalog_pool import primary_artist
from wavecast.intelligence.models import ResolvedTrack
from wavecast.stations import StationId
from wavecast.text_identity import base_title_key, canonical_name

ARTIST_ROUTE_CAP = 2
# Shorter titles ("Home", "Time") collide between unrelated songs, so a same-title check on
# them would reject songs that are merely similarly named.
_MIN_SHARED_TITLE_KEY = 6


def spread_cap(*, required_artists: Iterable[str], station: StationId | None) -> int | None:
    """Most plays one artist may have in this programme, or None when it is not limited."""

    if any(True for _ in required_artists) or station is StationId.PORTRAIT:
        return None
    return ARTIST_ROUTE_CAP


def _words(credit: str) -> frozenset[str]:
    return frozenset(canonical_name(primary_artist(credit)).split())


def same_artist(left: str, right: str) -> bool:
    """Same lead artist; "Bill Evans" and "Bill Evans Trio" count as one."""

    a, b = canonical_name(primary_artist(left)), canonical_name(primary_artist(right))
    if not a or not b:
        return False
    if a == b:
        return True
    words_a, words_b = _words(left), _words(right)
    return len(words_a) > 0 and len(words_b) > 0 and (words_a <= words_b or words_b <= words_a)


def artist_plays(artist: str, tracks: Iterable[ResolvedTrack]) -> int:
    return sum(1 for track in tracks if same_artist(track.canonical_artist, artist))


def at_artist_cap(artist: str, tracks: Iterable[ResolvedTrack], cap: int | None) -> bool:
    return cap is not None and artist_plays(artist, tracks) >= cap


def same_song_other_artist(left: ResolvedTrack, right: ResolvedTrack) -> bool:
    """The same long-enough title under a different artist: a cover or another take.

    Not applied by callers to programmes about covers or lineage, where that is the point.
    """

    if same_artist(left.canonical_artist, right.canonical_artist):
        return False
    key = base_title_key(left.canonical_title)
    return len(key) >= _MIN_SHARED_TITLE_KEY and key == base_title_key(right.canonical_title)
