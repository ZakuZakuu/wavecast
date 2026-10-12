"""A chapter's text must describe the track the catalog actually bound to it.

The Curator plans a chapter (reason, narration goal, evidence) around a track *hypothesis*.
Resolution may then play a different one: an alternate when the first choice is not in the
catalog, or a track whose artist is not the one the chapter text is about.  The Writer trusts
the chapter text, so the host would talk about an artist the listener is not hearing.

These pure helpers detect that and give the chapter neutral, track-true text instead.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from wavecast.catalog_pool import artist_credit_includes, split_artists
from wavecast.coverage import candidate_artist_names
from wavecast.intelligence.models import ChapterPlan, TrackProposal
from wavecast.text_identity import canonical_name, text_mentions_name


def known_artist_names(
    proposals: Iterable[TrackProposal], required: Sequence[str], topic: str
) -> list[str]:
    """Artist names the plan could write about: proposed, requested, or named in the request."""

    names: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        key = canonical_name(name)
        if len(key) >= 2 and key not in seen:
            seen.add(key)
            names.append(name)

    for name in required:
        add(name)
    for name in candidate_artist_names(topic, limit=6):
        add(name)
    for proposal in proposals:
        add(proposal.artist)
    return names


def chapter_text(chapter: ChapterPlan) -> str:
    """Everything in the chapter plan that the Writer is told about the track."""

    parts = [chapter.reason, chapter.narration_goal]
    if chapter.connection_from_previous_track is not None:
        parts.append(chapter.connection_from_previous_track.rationale)
    parts.extend(support.claim for support in chapter.claim_support)
    return "\n".join(parts)


def foreign_artists(
    chapter: ChapterPlan,
    bound_credit: str,
    known: Sequence[str],
    played_before: Sequence[str],
) -> list[str]:
    """Artists the chapter text is about that are not the bound track's.

    A name counts when the text writes it, it is not part of the bound credit, and the
    listener has not already heard it (so looking back at an earlier track is fine).  A text
    that also names the bound artist is a bridge between the two and is left alone.
    """

    text = chapter_text(chapter)
    if any(
        text_mentions_name(text, part)
        for part in _credit_parts(bound_credit)
    ):
        return []
    found: list[str] = []
    for name in known:
        if any(artist_credit_includes(credit, name) for credit in played_before):
            continue
        if text_mentions_name(text, name) and name not in found:
            found.append(name)
    return found


def _credit_parts(credit: str) -> list[str]:
    parts = list(split_artists(credit))
    return parts or [credit]


def used_an_alternate(chapter: ChapterPlan, selected: TrackProposal | None) -> bool:
    """True when the track that plays is not the proposal the chapter was planned around."""

    if chapter.track is None or selected is None:
        return False
    return (
        canonical_name(chapter.track.artist) != canonical_name(selected.artist)
        or canonical_name(chapter.track.title) != canonical_name(selected.title)
    )


def track_true_chapter(chapter: ChapterPlan, selected: TrackProposal | None) -> ChapterPlan:
    """The chapter with its text, claims and evidence reduced to what the played track supports.

    The editorial role and position stay; the reason, goal, connection, claims and the
    evidence of the planned track go, so the host says only generic, true things about it.
    """

    return chapter.model_copy(
        update={
            "track": selected,
            "track_alternates": [],
            "connection_from_previous_track": None,
            "reason": (
                "Use a catalog-resolved replacement while preserving this chapter's "
                "editorial role."
            ),
            "novelty_distance": (
                selected.novelty_distance if selected is not None else chapter.novelty_distance
            ),
            "evidence_ids": list(selected.evidence_ids) if selected is not None else [],
            "claim_support": [],
            "narration_goal": (
                "Connect this playable replacement to the programme direction without "
                "unsupported song-specific claims."
            ),
        }
    )
