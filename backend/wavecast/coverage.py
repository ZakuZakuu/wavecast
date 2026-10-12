"""Making the route honour what the listener asked for.

A request such as “from Mogwai to Explosions in the Sky” names artists the programme must
actually play.  The Curator plans from a candidate pool and from memory, so it can leave one
out (or give a chapter about artist B a track by artist A).  These pure helpers

* find artist names worth searching in the request text,
* check which required artists the planned or final route plays, and
* patch the plan from verified-playable pool entries when one is missing.

A required artist that cannot be covered is reported as unfulfilled, so the host never claims it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from wavecast.catalog_pool import CatalogPool, PoolEntry, artist_credit_includes
from wavecast.intelligence.models import (
    ChapterPlan,
    Evidence,
    NarrativeRole,
    NoveltyDistance,
    ResolvedTrack,
    TrackProposal,
)
from wavecast.text_identity import canonical_name

# Words that read like a name in a request but name a style, not an artist.
_GENERIC_PHRASES = frozenset(
    {
        "city pop", "post rock", "post-rock", "jazz", "rock", "pop", "piano", "bgm", "ost",
        "lo-fi", "lofi", "hip hop", "hip-hop", "indie", "folk", "blues", "soul", "funk",
        "classical", "electronic", "ambient", "playlist", "music", "live", "remix",
    }
)
_LATIN_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’&.\-]*(?: [A-Za-z0-9'’&.\-]+)*")
# Lower-case words a name may contain between capitalised ones (“Explosions in the Sky”).
_NAME_CONNECTORS = frozenset({"in", "the", "of", "de", "la", "le", "a", "an", "on", "at"})

# Roles whose track can change without breaking the programme's arc, in order of preference.
_MOVABLE_ROLES = (
    NarrativeRole.DISCOVERY,
    NarrativeRole.CONTRAST,
    NarrativeRole.VALIDATION,
    NarrativeRole.BRIDGE,
)


def candidate_artist_names(text: str, *, limit: int = 3) -> list[str]:
    """Latin-script name-like phrases in a request (“Mogwai”, “Explosions in the Sky”).

    A name starts and ends with a capitalised (or numeric) word; lower-case words in between
    must be connectors, so “Mogwai live” gives “Mogwai” and “late night drive” gives nothing.
    Only a hint for what to search: a phrase that is not an artist finds no tracks credited
    to it and is dropped by the pool.
    """

    names: list[str] = []
    for match in _LATIN_RUN.finditer(text):
        for phrase in _name_phrases(match.group(0)):
            folded = canonical_name(phrase)
            if len(folded) < 3 or folded in _GENERIC_PHRASES:
                continue
            if all(canonical_name(existing) != folded for existing in names):
                names.append(phrase)
            if len(names) >= limit:
                return names
    return names


def _name_phrases(run: str) -> list[str]:
    phrases: list[str] = []
    current: list[str] = []

    def flush() -> None:
        while current and current[-1].casefold() in _NAME_CONNECTORS:
            current.pop()
        if current:
            phrases.append(" ".join(current).strip(" .-&'’"))
        current.clear()

    for word in run.split():
        if word[0].isupper() or word[0].isdigit():
            current.append(word)
        elif current and word.casefold() in _NAME_CONNECTORS:
            current.append(word)
        else:
            flush()
    flush()
    return phrases


def entries_for_artist(pool: CatalogPool | None, artist: str) -> list[PoolEntry]:
    if pool is None:
        return []
    return [entry for entry in pool.entries if artist_credit_includes(entry.artist, artist)]


def covered_artists(required: Sequence[str], credits: Sequence[str]) -> list[str]:
    """The required artists that at least one credit names."""

    return [
        name for name in required if any(artist_credit_includes(credit, name) for credit in credits)
    ]


def unfulfilled_artists(required: Sequence[str], tracks: Sequence[ResolvedTrack]) -> list[str]:
    """Required artists the final route does not play."""

    credits = [track.canonical_artist for track in tracks]
    done = set(covered_artists(required, credits))
    return [name for name in required if name not in done]


def rebind_chapter(
    chapter: ChapterPlan, proposal: TrackProposal, evidence: Sequence[Evidence], artist: str
) -> ChapterPlan:
    """The chapter, now about ``proposal``: its intent and evidence follow the new track.

    Only evidence that actually mentions ``artist`` is kept, so the host cannot talk about
    someone else's facts over this track.
    """

    folded = canonical_name(artist)
    related = [item.id for item in evidence if folded and folded in canonical_name(item.claim_or_excerpt)]
    return chapter.model_copy(
        update={
            "track": proposal,
            "track_alternates": [],
            "connection_from_previous_track": None,
            "reason": f"Bring in {artist}, which the listener's request names.",
            "novelty_distance": proposal.novelty_distance,
            "evidence_ids": related[:3],
            "claim_support": [],
            "narration_goal": (
                f"Introduce {artist} with the supported facts, then connect it to the track "
                "before it, without claims about other artists."
            ),
        }
    )


def ensure_required_coverage(
    chapters: Sequence[ChapterPlan],
    pool: CatalogPool | None,
    required: Sequence[str],
    evidence: Sequence[Evidence],
    *,
    reserved: Sequence[ResolvedTrack] = (),
    protected_indices: Sequence[int] = (0,),
) -> tuple[list[ChapterPlan], list[str]]:
    """Patch the plan so every required artist with a playable pool entry is in it.

    Returns the chapters and the required artists that remain uncovered.  Only a chapter whose
    track is by no required artist is swapped, preferring one whose artist repeats; the
    protected chapters (the opening, a locked successor) are never touched.  Alternates do not
    count as coverage: they only play when the primary cannot.
    """

    result = list(chapters)
    missing: list[str] = []
    credits = [track.canonical_artist for track in reserved]
    credits.extend(chapter.track.artist for chapter in result if chapter.track is not None)

    for name in required:
        if covered_artists([name], credits):
            continue
        entries = entries_for_artist(pool, name)
        target = _movable_chapter(result, required, protected_indices)
        if not entries or target is None:
            missing.append(name)
            continue
        entry = entries[0]
        proposal = TrackProposal(
            artist=entry.artist,
            title=entry.title,
            reasons=["Required by the listener's request."],
            confidence=0.6,
            novelty_distance=result[target].novelty_distance or NoveltyDistance.CLOSE,
        )
        result[target] = rebind_chapter(result[target], proposal, evidence, name)
        credits.append(entry.artist)
    return result, missing


def _movable_chapter(
    chapters: Sequence[ChapterPlan], required: Sequence[str], protected: Sequence[int]
) -> int | None:
    """The chapter to give to a missing artist.

    Not a protected chapter, and not one that already plays a required artist.  A repeated
    artist is given up before a lone one; then a role that can change without breaking the
    arc; the closing chapter last.
    """

    counts: dict[str, int] = {}
    for chapter in chapters:
        if chapter.track is not None:
            key = canonical_name(chapter.track.artist.split(",")[0])
            counts[key] = counts.get(key, 0) + 1
    last_index = max((index for index, chapter in enumerate(chapters) if chapter.track), default=-1)
    best: tuple[int, int] | None = None
    for index, chapter in enumerate(chapters):
        if index in protected or chapter.track is None:
            continue
        if covered_artists(required, [chapter.track.artist]):
            continue
        key = canonical_name(chapter.track.artist.split(",")[0])
        rank = (
            _MOVABLE_ROLES.index(chapter.narrative_role)
            if chapter.narrative_role in _MOVABLE_ROLES
            else len(_MOVABLE_ROLES)
        )
        score = (
            (0 if counts.get(key, 0) > 1 else 1000)
            + rank * 100
            + (50 if index == last_index else 0)
            - index
        )
        if best is None or score < best[0]:
            best = (score, index)
    return best[1] if best else None
