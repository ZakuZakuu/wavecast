"""Typed curator: chooses a listening arc without any search dependency."""

from __future__ import annotations

import json
from collections.abc import Sequence

from wavecast.providers.profiles import InferenceProfile, StructuredTransport

from .fast_start import FastStructuredProvider
from .models import (
    ChapterPlan,
    FastStartPlan,
    NoveltyDistance,
    OutputLanguage,
    ProgramSkeleton,
    ResearchBundle,
    TrackProposal,
    resolve_output_language,
)
from .trace import GenerationTrace


class CuratorContractError(ValueError):
    """A parsed Curator result violated an application-owned invariant."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        diagnostics: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.diagnostics = diagnostics or []


class CuratorService:
    def __init__(self, llm: FastStructuredProvider) -> None:
        self.llm = llm

    async def curate(
        self,
        bundle: ResearchBundle,
        fast_plan: FastStartPlan,
        *,
        desired_duration_seconds: int,
        max_tracks: int = 4,
        max_chapters: int = 16,
        committed_chapters: list[ChapterPlan] | None = None,
        output_language: OutputLanguage = OutputLanguage.AUTO,
        topic: str = "",
        trace: GenerationTrace | None = None,
    ) -> ProgramSkeleton:
        committed = committed_chapters or []
        research_context, fast_context = _build_curator_context(bundle, fast_plan)
        prompt = (
            "Sequence a deliberate chapter-ordered response to the listener's actual topic "
            "from normalized research, the FastStart plan, and the ResearchPlan. This may be a "
            "career, creative-work, analysis, history/context, or music-discovery request; "
            "adapt the editorial arc to the topic rather than assuming a similarity playlist. "
            "Playback order is exactly chapter order. Search is complete; do not request or "
            "invent web evidence. Each chapter is one narrative beat with zero or one supporting "
            "TrackProposal; do not add unrelated artists only to manufacture novelty. Keep a "
            "stable or repeated novelty distance when a meaningful move is not justified. "
            "A chapter is a narrative beat and may intentionally have no TrackProposal; do not "
            "invent a track to fill a story beat. "
            f"Return no more than {max_chapters} chapters total and no more than "
            f"{max_tracks} chapters with a TrackProposal. A track-bearing chapter may "
            "include up to two ranked track_alternates only when they satisfy the same editorial "
            "role and transition intent as the primary; alternates are playback recovery options, "
            "not extra chapters or unrelated backup artists. Narrative-only beats must serve the actual topic "
            "rather than expanding the episode just to fill duration. "
            "For explicit music-discovery or artist-to-artist, scene, genre, or lineage "
            "route requests, when grounded candidates support it and max_tracks is at least "
            "3, prefer a 3-5 track-bearing listening arc rather than a brittle two-track "
            "route. Every selected track must be an actual program chapter with a clear "
            "editorial purpose; these are not alternate or unused backup proposals, and "
            "do not add unrelated tracks merely to reach the range. If the evidence does "
            "not support that many meaningful tracks, select fewer. "
            "For every factual, correlation, causal, editorial-interpretation, or uncertainty "
            "statement in a chapter, use typed claim_support with one or more evidence IDs from "
            "that chapter's evidence_ids. Keep correlation distinct from proven causation; do "
            "not make an unsupported claim merely because a source is preferred. "
            "For every track-bearing chapter after the first selected track-bearing chapter, "
            "add a typed connection_from_previous_track describing the previous selected chapter "
            "to the current selected chapter. This is a pre-resolution editorial-selection "
            "relation, not a claim about playable catalog adjacency. Use one relation_type, "
            "concise musical_dimensions, a topic-specific rationale, and only evidence IDs "
            "scoped to that chapter. Narrative-only beats do not need a connection. "
            "novelty_distance may start at any supported "
            "distance; distances may be skipped, and repeated distances are allowed when "
            "intended. The sequence must never move backward: very_close <= close <= bridge "
            "<= discovery <= surprise. For example, [\"close\", \"bridge\", \"discovery\"] "
            "is valid, while [\"close\", \"surprise\", \"bridge\"] is invalid. Preserve "
            "committed chapters exactly and place speculative chapters after committed chapters. "
            "Define the distances semantically: very_close keeps the same core sonic identity; "
            "close introduces at least one new musical dimension; bridge connects anchor traits "
            "to a different artist, scene, or era; discovery leaves the immediate cluster while "
            "remaining strongly justified; surprise is less obvious but still coherent. Do not "
            "label a track discovery merely because it appears later. Unless the topic asks for "
            "a single-artist deep dive, later bridge/discovery chapters should introduce new "
            "artists or scenes only when they answer the topic. Use each chapter reason as a concise "
            "topic-specific rationale.\n"
            f"Research context: {_compact_json(research_context)}\n"
            f"FastStart context: {_compact_json(fast_context)}\n"
            f"Committed: {_compact_json([item.model_dump(mode='json') for item in committed])}\n"
            f"Duration: {desired_duration_seconds}\n"
            f"Output language: {resolve_output_language(output_language, topic).value}"
        )
        skeleton = await self.llm.structured(
            prompt,
            ProgramSkeleton,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=InferenceProfile.CURATOR,
            stage="curator",
        )
        if not isinstance(skeleton, ProgramSkeleton):
            raise TypeError("curator returned an unexpected output model")
        normalized, diagnostics = normalize_curator_skeleton(skeleton, bundle)
        if trace:
            for diagnostic in diagnostics:
                trace.mark("curator_reference_normalized", **diagnostic)
        _validate_curator_contract(normalized, bundle)
        normalized = _restore_committed_prefix(normalized, committed)
        return ensure_distance_curve(normalized)


def _build_curator_context(
    bundle: ResearchBundle,
    fast_plan: FastStartPlan,
) -> tuple[dict[str, object], dict[str, object]]:
    """Keep Curator context complete while avoiding duplicated payloads.

    ResearchPlan used to appear once through each of ResearchBundle,
    FastStartPlan, and an explicit prompt field. The Curator only needs one
    canonical copy; the first non-empty source is the application-owned one.
    first_narration is an immediate playback artifact and is intentionally not
    part of editorial selection context.
    """

    research_plan = bundle.research_plan or fast_plan.research_plan
    research_context = {
        "anchors": bundle.anchors,
        "taste_hypotheses": [
            item.model_dump(mode="json") for item in bundle.taste_hypotheses
        ],
        "evidence": [item.model_dump(mode="json") for item in bundle.evidence],
        "candidates": [item.model_dump(mode="json") for item in bundle.candidates],
        "research_plan": research_plan.model_dump(mode="json") if research_plan else None,
        "uncertainties": bundle.uncertainties,
    }
    fast_context = {
        "anchor_understanding": fast_plan.anchor_understanding,
        "immediate_taste_hypotheses": [
            item.model_dump(mode="json") for item in fast_plan.immediate_taste_hypotheses
        ],
        "next_candidates": [
            item.model_dump(mode="json") for item in fast_plan.next_candidates
        ],
        "selected_next_track": (
            fast_plan.selected_next_track.model_dump(mode="json")
            if fast_plan.selected_next_track
            else None
        ),
        "uncertainties": fast_plan.uncertainties,
    }
    return research_context, fast_context


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_curator_skeleton(
    skeleton: ProgramSkeleton,
    bundle: ResearchBundle,
) -> tuple[ProgramSkeleton, list[dict[str, object]]]:
    """Normalize recoverable curator mistakes before strict validation.

    The model is not authoritative for evidence references or structural relation
    placement. Unknown references are removed, unsupported claim blocks are
    dropped, and a connection attached to a narrative-only chapter is discarded
    rather than failing the entire progressive episode.
    """

    available = {item.id for item in bundle.evidence}
    diagnostics: list[dict[str, object]] = []
    chapters: list[ChapterPlan] = []
    for chapter in skeleton.chapters:
        chapter_ids, dropped, remaining = _retain_evidence_ids(
            chapter.evidence_ids, available
        )
        if dropped:
            diagnostics.append(
                _normalization_diagnostic(
                    chapter.index,
                    "chapter_evidence",
                    dropped,
                    remaining,
                )
            )
        chapter_scope = set(chapter_ids)
        supports = []
        for support in chapter.claim_support:
            support_ids, dropped, remaining = _retain_evidence_ids(
                support.evidence_ids, available & chapter_scope
            )
            if dropped:
                diagnostics.append(
                    _normalization_diagnostic(
                        chapter.index,
                        "claim_support",
                        dropped,
                        remaining,
                    )
                )
            if support_ids:
                supports.append(support.model_copy(update={"evidence_ids": support_ids}))
        track = chapter.track
        alternates: list[TrackProposal] = []
        if track is not None:
            track_ids, dropped, remaining = _retain_evidence_ids(track.evidence_ids, available)
            if dropped:
                diagnostics.append(
                    _normalization_diagnostic(
                        chapter.index,
                        "track_evidence",
                        dropped,
                        remaining,
                    )
                )
            track = track.model_copy(update={"evidence_ids": track_ids})
            seen_track_keys = {(track.artist.casefold().strip(), track.title.casefold().strip())}
            for alternate in chapter.track_alternates:
                alternate_ids, dropped, remaining = _retain_evidence_ids(
                    alternate.evidence_ids, available
                )
                if dropped:
                    diagnostics.append(
                        _normalization_diagnostic(
                            chapter.index,
                            "track_alternate_evidence",
                            dropped,
                            remaining,
                        )
                    )
                normalized_alternate = alternate.model_copy(
                    update={"evidence_ids": alternate_ids}
                )
                key = (
                    normalized_alternate.artist.casefold().strip(),
                    normalized_alternate.title.casefold().strip(),
                )
                if key in seen_track_keys:
                    diagnostics.append(
                        _normalization_diagnostic(
                            chapter.index,
                            "duplicate_track_alternate",
                            1,
                            len(alternates),
                        )
                    )
                    continue
                seen_track_keys.add(key)
                alternates.append(normalized_alternate)
        elif chapter.track_alternates:
            diagnostics.append(
                _normalization_diagnostic(
                    chapter.index,
                    "track_alternates_without_primary",
                    len(chapter.track_alternates),
                    0,
                )
            )
        connection = chapter.connection_from_previous_track
        if connection is not None:
            connection_ids, dropped, remaining = _retain_evidence_ids(
                connection.evidence_ids, available & chapter_scope
            )
            if dropped:
                diagnostics.append(
                    _normalization_diagnostic(
                        chapter.index,
                        "connection_evidence",
                        dropped,
                        remaining,
                    )
                )
            connection = connection.model_copy(update={"evidence_ids": connection_ids})
        if track is None and connection is not None:
            diagnostics.append(
                _normalization_diagnostic(
                    chapter.index,
                    "connection_without_track",
                    1,
                    0,
                )
            )
            connection = None
        chapters.append(
            chapter.model_copy(
                update={
                    "evidence_ids": chapter_ids,
                    "claim_support": supports,
                    "track": track,
                    "track_alternates": alternates,
                    "connection_from_previous_track": connection,
                }
            )
        )
    return skeleton.model_copy(update={"chapters": chapters}), diagnostics


def _retain_evidence_ids(
    evidence_ids: Sequence[str], available: set[str]
) -> tuple[list[str], int, int]:
    retained: list[str] = []
    seen: set[str] = set()
    for evidence_id in evidence_ids:
        if evidence_id in available and evidence_id not in seen:
            retained.append(evidence_id)
            seen.add(evidence_id)
    return retained, len(evidence_ids) - len(retained), len(retained)


def _normalization_diagnostic(
    chapter_index: int,
    reference_kind: str,
    dropped_reference_count: int,
    remaining_reference_count: int,
) -> dict[str, object]:
    return {
        "chapter_index": chapter_index,
        "reference_kind": reference_kind,
        "dropped_reference_count": dropped_reference_count,
        "remaining_reference_count": remaining_reference_count,
    }


def _validate_curator_contract(skeleton: ProgramSkeleton, bundle: ResearchBundle) -> None:
    available = {item.id for item in bundle.evidence}
    for chapter in skeleton.chapters:
        scoped = set(chapter.evidence_ids)
        if not scoped <= available:
            raise CuratorContractError(
                "curator chapter evidence scope is invalid",
                reason_code="curator_chapter_evidence_scope_invalid",
            )
        for support in chapter.claim_support:
            referenced = set(support.evidence_ids)
            if not referenced or not referenced <= scoped or not referenced <= available:
                raise CuratorContractError(
                    "curator claim support evidence scope is invalid",
                    reason_code="curator_claim_support_scope_invalid",
                )
        if chapter.track is not None and not set(chapter.track.evidence_ids) <= available:
            raise CuratorContractError(
                "curator track evidence scope is invalid",
                reason_code="curator_track_evidence_scope_invalid",
            )
        if chapter.track is None and chapter.track_alternates:
            raise CuratorContractError(
                "curator track alternates require a primary track",
                reason_code="curator_track_alternates_require_primary",
            )
        for alternate in chapter.track_alternates:
            if not set(alternate.evidence_ids) <= available:
                raise CuratorContractError(
                    "curator alternate track evidence scope is invalid",
                    reason_code="curator_track_alternate_evidence_scope_invalid",
                )
        connection = chapter.connection_from_previous_track
        if connection is not None:
            if chapter.track is None:
                raise CuratorContractError(
                    "curator connection requires a track-bearing chapter",
                    reason_code="curator_connection_requires_track",
                )
            if not set(connection.evidence_ids) <= scoped or not set(
                connection.evidence_ids
            ) <= available:
                raise CuratorContractError(
                    "curator connection evidence scope is invalid",
                    reason_code="curator_connection_evidence_scope_invalid",
                )


def _restore_committed_prefix(
    skeleton: ProgramSkeleton, committed_chapters: Sequence[ChapterPlan]
) -> ProgramSkeleton:
    """Keep already committed chapter models byte-for-byte stable across curation."""

    if not committed_chapters:
        return skeleton
    committed_by_index = {chapter.index: chapter for chapter in committed_chapters}
    chapters = [
        committed_by_index.get(chapter.index, chapter) for chapter in skeleton.chapters
    ]
    return skeleton.model_copy(update={"chapters": chapters})


def ensure_distance_curve(skeleton: ProgramSkeleton) -> ProgramSkeleton:
    """Clamp recoverable backward novelty labels without changing chapter order.

    Novelty distance is editorial metadata, not catalog identity or evidence.
    A single backward label should not turn an otherwise grounded progressive
    route into a production 500. Preserve earlier/committed chapters exactly and
    raise only later labels to the last established distance.
    """

    order = {
        NoveltyDistance.VERY_CLOSE: 1,
        NoveltyDistance.CLOSE: 2,
        NoveltyDistance.BRIDGE: 3,
        NoveltyDistance.DISCOVERY: 4,
        NoveltyDistance.SURPRISE: 5,
    }
    by_rank = {rank: distance for distance, rank in order.items()}
    floor = 0
    chapters: list[ChapterPlan] = []
    for chapter in skeleton.chapters:
        distance = chapter.novelty_distance
        if distance is None:
            chapters.append(chapter)
            continue
        rank = order[distance]
        if rank >= floor:
            floor = rank
            chapters.append(chapter)
            continue

        normalized_distance = by_rank[floor]
        track = chapter.track
        if track is not None and track.novelty_distance is not None:
            track = track.model_copy(update={"novelty_distance": normalized_distance})
        chapters.append(
            chapter.model_copy(
                update={
                    "novelty_distance": normalized_distance,
                    "track": track,
                }
            )
        )

    # Curator order and chapter indices are part of the narrative contract. Do not
    # sort or renumber here: committed-prefix validation relies on exact identity.
    return skeleton.model_copy(update={"chapters": chapters})
