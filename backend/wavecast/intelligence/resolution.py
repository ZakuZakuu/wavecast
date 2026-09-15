"""Deterministic boundary between intelligence proposals and playable tracks."""

from __future__ import annotations

from wavecast.models.episode import Segment, SegmentKind, SegmentState
from wavecast.providers.contracts import MusicProvider, TrackMetadata

from .models import (
    ResolvedTrack,
    ResolvedTrackCandidate,
    TrackCandidate,
    TrackProposal,
    UnresolvedTrackError,
)


def _same_catalog_name(left: str, right: str) -> bool:
    return " ".join(left.casefold().split()) == " ".join(right.casefold().split())


def _resolved_track(metadata: TrackMetadata) -> ResolvedTrack | None:
    if not metadata.playable:
        return None
    return ResolvedTrack(
        track_ref=metadata.track_ref,
        canonical_artist=metadata.artist,
        canonical_title=metadata.title,
    )


async def resolve_track_proposal(
    provider: MusicProvider, proposal: TrackProposal | TrackCandidate
) -> ResolvedTrack | None:
    """Resolve an artist/title proposal against the existing MusicProvider seam.

    Search results are accepted only when both artist and title match the catalog's
    canonical values.  A webpage title or event listing therefore remains evidence or
    an unresolved proposal; it is never promoted by string heuristics.
    """

    if isinstance(proposal, TrackCandidate) and proposal.track_ref:
        try:
            return _resolved_track(await provider.resolve_track(proposal.track_ref))
        except (KeyError, ValueError):
            return None

    results = await provider.search(proposal.title)
    for metadata in results:
        if _same_catalog_name(metadata.artist, proposal.artist) and _same_catalog_name(
            metadata.title, proposal.title
        ):
            return _resolved_track(metadata)
    return None


async def resolve_track_candidate(
    provider: MusicProvider, proposal: TrackProposal | TrackCandidate
) -> ResolvedTrackCandidate | None:
    """Return the proposal enriched with stable catalog identity when available."""

    resolved = await resolve_track_proposal(provider, proposal)
    if resolved is None:
        return None
    if isinstance(proposal, TrackCandidate):
        return ResolvedTrackCandidate(
            **proposal.model_dump(
                exclude={"track_ref", "canonical_artist", "canonical_title"}
            ),
            track_ref=resolved.track_ref,
            canonical_artist=resolved.canonical_artist,
            canonical_title=resolved.canonical_title,
        )
    return ResolvedTrackCandidate(
        **proposal.model_dump(),
        track_ref=resolved.track_ref,
        canonical_artist=resolved.canonical_artist,
        canonical_title=resolved.canonical_title,
    )


def music_segment_from_track(
    track: ResolvedTrack | TrackProposal | TrackCandidate,
    *,
    chapter_id: str,
    order: int,
    planned_duration_seconds: int = 1,
    state: SegmentState = SegmentState.PLANNED,
) -> Segment:
    """Build a timeline music segment only from a resolved catalog identity."""

    if isinstance(track, ResolvedTrack):
        resolved = track
    elif isinstance(track, TrackCandidate) and track.is_resolved:
        resolved = track.resolved_track()
    else:
        raise UnresolvedTrackError("unresolved track proposal cannot enter the audio timeline")
    return Segment(
        chapter_id=chapter_id,
        order=order,
        kind=SegmentKind.MUSIC,
        state=state,
        planned_duration_seconds=planned_duration_seconds,
        track_ref=resolved.track_ref,
        title=resolved.canonical_title,
        artist=resolved.canonical_artist,
    )
