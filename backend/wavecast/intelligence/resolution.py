"""Deterministic boundary between intelligence proposals and playable tracks."""

from __future__ import annotations

from wavecast.models.episode import MusicSegment, SegmentKind, SegmentState
from wavecast.providers.contracts import MusicProvider, TrackMetadata
from wavecast.providers.errors import ProviderError
from wavecast.providers.retrieval import MusicRetrievalService

from .models import (
    ResolvedTrack,
    ResolvedTrackCandidate,
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


def _exact_identity(metadata: TrackMetadata, proposal: TrackProposal) -> bool:
    return _same_catalog_name(metadata.artist, proposal.artist) and _same_catalog_name(
        metadata.title, proposal.title
    )


async def _resolve_exact_metadata(
    provider: MusicProvider,
    proposal: TrackProposal,
    metadata: TrackMetadata,
) -> ResolvedTrack | None:
    """Confirm exact search identity and, when needed, detail-level playability."""

    if not _exact_identity(metadata, proposal):
        return None
    fast_path = _resolved_track(metadata)
    if fast_path is not None:
        return fast_path

    try:
        detailed = await provider.resolve_track(metadata.track_ref)
    except ProviderError:
        return None
    if not isinstance(detailed, TrackMetadata) or not _exact_identity(detailed, proposal):
        return None
    return _resolved_track(detailed)


async def resolve_track_proposal(
    provider: MusicProvider, proposal: TrackProposal
) -> ResolvedTrack | None:
    """Resolve an artist/title proposal against the existing MusicProvider seam.

    Search results are accepted only when both artist and title match the catalog's
    canonical values.  A webpage title or event listing therefore remains evidence or
    an unresolved proposal; it is never promoted by string heuristics.
    """

    results = await provider.search(proposal.title)
    for metadata in results:
        resolved = await _resolve_exact_metadata(provider, proposal, metadata)
        if resolved is not None:
            return resolved
    return None


async def resolve_track_candidate(
    provider: MusicProvider, proposal: TrackProposal
) -> ResolvedTrackCandidate | None:
    """Return the proposal enriched with stable catalog identity when available."""

    resolved = await resolve_track_proposal(provider, proposal)
    if resolved is None:
        return None
    return ResolvedTrackCandidate(
        **proposal.model_dump(),
        track_ref=resolved.track_ref,
        canonical_artist=resolved.canonical_artist,
        canonical_title=resolved.canonical_title,
    )


async def resolve_track_proposal_across_providers(
    retrieval: MusicRetrievalService,
    proposal: TrackProposal,
    *,
    limit: int = 10,
) -> ResolvedTrack | None:
    """Resolve a proposal through deterministic multi-catalog retrieval.

    Exact artist and full-title identity checks remain mandatory.  Retrieval may
    rank base-title/version alternatives, but it cannot silently promote a
    near-match or an unqualified provider reference into the episode timeline.
    """
    combined_query = f"{proposal.artist} {proposal.title}"
    queries = [combined_query]
    if proposal.title and proposal.title != combined_query:
        queries.append(proposal.title)

    for query in queries:
        candidates = await retrieval.search(
            query,
            requested_artist=proposal.artist,
            requested_title=proposal.title,
            limit=limit,
        )
        for candidate in candidates:
            if not candidate.track_ref.startswith(f"{candidate.provider}:"):
                continue
            if not _same_catalog_name(candidate.artist, proposal.artist) or not _same_catalog_name(
                candidate.title, proposal.title
            ):
                continue
            if candidate.playable:
                return ResolvedTrack(
                    track_ref=candidate.track_ref,
                    canonical_artist=candidate.artist,
                    canonical_title=candidate.title,
                )
            try:
                provider = retrieval.registry.provider_for_track_ref(candidate.track_ref)
            except ProviderError:
                continue
            metadata = TrackMetadata(
                track_ref=candidate.track_ref,
                title=candidate.title,
                artist=candidate.artist,
                duration_seconds=candidate.duration_seconds,
                playable=candidate.playable,
                metadata=candidate.metadata,
            )
            resolved = await _resolve_exact_metadata(provider, proposal, metadata)
            if resolved is not None:
                return resolved
    return None


def music_segment_from_track(
    track: ResolvedTrack | ResolvedTrackCandidate,
    *,
    chapter_id: str,
    order: int,
    planned_duration_seconds: int = 1,
    state: SegmentState = SegmentState.PLANNED,
) -> MusicSegment:
    """Build a timeline music segment only from a resolved catalog identity."""

    if isinstance(track, ResolvedTrack):
        resolved = track
    elif isinstance(track, ResolvedTrackCandidate):
        resolved = track.resolved_track()
    else:
        raise UnresolvedTrackError("unresolved track proposal cannot enter the audio timeline")
    return MusicSegment(
        chapter_id=chapter_id,
        order=order,
        kind=SegmentKind.MUSIC,
        state=state,
        planned_duration_seconds=planned_duration_seconds,
        track_ref=resolved.track_ref,
        title=resolved.canonical_title,
        artist=resolved.canonical_artist,
    )
