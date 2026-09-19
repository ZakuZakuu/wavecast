"""Typed, human-in-the-loop quality artifacts for Guided Discovery.

The evaluator deliberately assembles review material instead of producing an automatic
quality pass.  A valid schema and a monotonic curve are runtime invariants, not a claim
that the resulting program is musically good.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from wavecast.intelligence.models import (
    FastStartPlan,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    ResolvedTrackCandidate,
    TasteHypothesis,
    TrackProposal,
)


class QualityDimension(StrEnum):
    # Legacy dimensions remain available for existing fixture reports.
    TASTE_DEPTH = "TasteDepth"
    CANDIDATE_VALIDITY = "CandidateValidity"
    LOCAL_COHERENCE = "LocalCoherence"
    DISCOVERY_RADIUS = "DiscoveryRadius"
    NOVELTY_CALIBRATION = "NoveltyCalibration"
    NARRATIVE_ARC = "NarrativeArc"
    EVIDENCE_DISCIPLINE = "EvidenceDiscipline"
    EDITORIAL_THESIS = "EditorialThesis"
    DISCOVERY_VALUE = "DiscoveryValue"
    ROUTE_COHERENCE = "RouteCoherence"
    MUSICAL_INSIGHT = "MusicalInsight"
    RESEARCH_GROUNDING = "ResearchGrounding"
    NARRATIVE_PACING = "NarrativePacing"
    AFTER_LISTENING_EFFECT = "AfterListeningEffect"
    SPOKEN_WRITING_QUALITY = "SpokenWritingQuality"
    TTS_DELIVERY_STYLE_FIT = "TTSDeliveryStyleFit"


class GuidedDiscoveryCase(BaseModel):
    """A bounded benchmark input; expected answers are intentionally not hard-coded."""

    case_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    topic: str = Field(min_length=1, max_length=400)
    anchor_tracks: list[str] = Field(default_factory=list)
    anchor_artists: list[str] = Field(default_factory=list)
    failure_mode: str = Field(min_length=1, max_length=160)
    expected_dimensions: list[str] = Field(default_factory=list)
    desired_duration_seconds: int = Field(gt=0, default=1800)
    benchmark_kind: str = Field(default="guided_discovery", min_length=1, max_length=80)
    required_route_artists: list[str] = Field(default_factory=list, max_length=8)
    minimum_distinct_artists: int | None = Field(default=None, ge=1, le=32)


class QualityRubric(BaseModel):
    """Review dimensions for humans; these are not deterministic pass/fail rules."""

    dimensions: dict[QualityDimension, str]
    human_review_questions: list[str]


class ReviewCandidate(BaseModel):
    artist: str
    title: str
    similarity_dimensions: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    novelty_distance: NoveltyDistance | None = None
    narrative_role: NarrativeRole | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    scene_cluster_rationale: str | None = None
    track_ref: str | None = None
    resolution_status: Literal["resolved", "unresolved"] = "unresolved"


class GuidedDiscoveryReview(BaseModel):
    case_id: str
    case_title: str
    taste_hypotheses: list[TasteHypothesis]
    candidates: list[ReviewCandidate]
    program_arc: list[ReviewCandidate]
    rubric: QualityRubric
    human_review_questions: list[str]
    quality_status: Literal["human_review_required"] = "human_review_required"


class HardCheckResult(BaseModel):
    """One deterministic observation; it never claims human quality."""

    name: str = Field(min_length=1, max_length=100)
    status: Literal["pass", "fail", "not_observed"]
    summary: str = Field(min_length=1, max_length=500)


class HumanReviewDimension(BaseModel):
    """A review slot that can remain unobserved until a full episode is heard."""

    dimension: QualityDimension
    status: Literal["observed", "not_observed"] = "not_observed"
    score: int | None = Field(default=None, ge=1, le=5)
    justification: str = ""
    reference: str | None = Field(default=None, max_length=160)


class Phase51Diagnostics(BaseModel):
    """Deterministic metrics for separating discovery failure modes."""

    proposed_candidate_count: int = Field(ge=0)
    selected_track_count: int = Field(ge=0)
    resolved_track_count: int = Field(ge=0)
    unresolved_track_count: int = Field(ge=0)
    distinct_artist_count: int = Field(ge=0)
    same_artist_run_length: int = Field(ge=0)
    duplicate_track_count: int = Field(ge=0)
    resolution_rate: float | None = Field(default=None, ge=0, le=1)
    novelty_distribution: dict[str, int] = Field(default_factory=dict)


class Phase51Evaluation(BaseModel):
    """Review artifact for Phase 5.1; quality remains human-reviewed."""

    case_id: str
    case_title: str
    hard_checks: list[HardCheckResult]
    diagnostics: Phase51Diagnostics
    human_review: list[HumanReviewDimension]
    quality_status: Literal["human_review_required"] = "human_review_required"


RUBRIC = QualityRubric(
    dimensions={
        QualityDimension.TASTE_DEPTH: "Does it identify meaningful musical dimensions beyond surface descriptors?",
        QualityDimension.CANDIDATE_VALIDITY: "Are artist/title pairs plausible and evidence-supported?",
        QualityDimension.LOCAL_COHERENCE: "Does each next step make sense from the previous one?",
        QualityDimension.DISCOVERY_RADIUS: "Does the program eventually leave the immediate artist/franchise/scene cluster?",
        QualityDimension.NOVELTY_CALIBRATION: "Is each novelty distance semantically believable?",
        QualityDimension.NARRATIVE_ARC: "Does the sequence feel like progressive discovery rather than a ranked list or syllabus?",
        QualityDimension.EVIDENCE_DISCIPLINE: "Do factual claims cite evidence IDs and mark uncertainty when needed?",
    },
    human_review_questions=[
        "Does this leave the immediate anchor cluster?",
        "Is the novelty labeling believable?",
        "Are the reasons musically specific?",
        "Does this feel like discovery?",
        "Would you want to keep listening?",
    ],
)


PHASE51_RUBRIC = QualityRubric(
    dimensions={
        QualityDimension.EDITORIAL_THESIS: "Can the episode's central editorial point be stated clearly?",
        QualityDimension.DISCOVERY_VALUE: "Does it lead the listener to worthwhile unfamiliar music?",
        QualityDimension.ROUTE_COHERENCE: "Does every musical move have a specific reason from the prior step?",
        QualityDimension.MUSICAL_INSIGHT: "Does the narration help the listener hear musical details, not just facts?",
        QualityDimension.RESEARCH_GROUNDING: "Are factual and relationship claims grounded and appropriately uncertain?",
        QualityDimension.NARRATIVE_PACING: "Does the episode progress without repetition or mid-program fatigue?",
        QualityDimension.AFTER_LISTENING_EFFECT: "Does the listener hear a familiar or new track differently afterward?",
        QualityDimension.SPOKEN_WRITING_QUALITY: "Does the script sound natural, specific, and speakable?",
        QualityDimension.TTS_DELIVERY_STYLE_FIT: "Do pacing, emphasis, pronunciation, and voice fit the program?",
    },
    human_review_questions=[
        "What is the episode's thesis in one sentence?",
        "Which track was a genuine discovery, and why did it feel earned?",
        "Which transition had the strongest or weakest editorial reason?",
        "Did the narration change how you heard any music?",
        "Would you keep listening or save a new track afterward?",
    ],
)


def build_phase51_evaluation(
    case: GuidedDiscoveryCase,
    fast_plan: FastStartPlan,
    skeleton: ProgramSkeleton | None,
    resolved_candidates: list[ResolvedTrackCandidate] | None = None,
) -> Phase51Evaluation:
    """Build deterministic observations without claiming automatic quality."""

    selected = [
        chapter.track
        for chapter in (skeleton.chapters if skeleton is not None else [])
        if chapter.track is not None
    ]
    keys = [(item.artist.casefold(), item.title.casefold()) for item in selected]
    duplicate_count = len(keys) - len(set(keys))
    artists = [item.artist.casefold() for item in selected]
    distinct_artists = len(set(artists))
    run_length = 0
    current_run = 0
    previous_artist: str | None = None
    for artist in artists:
        current_run = current_run + 1 if artist == previous_artist else 1
        run_length = max(run_length, current_run)
        previous_artist = artist

    required = {
        artist.casefold(): artist for artist in case.required_route_artists
    }
    missing = [
        display_name
        for normalized, display_name in required.items()
        if normalized not in set(artists)
    ]
    route_status: Literal["pass", "fail", "not_observed"]
    if required:
        route_status = "fail" if missing else "pass"
        route_summary = (
            f"Missing required route artist(s): {', '.join(missing)}"
            if missing
            else "All benchmark-specific route artists are present."
        )
    elif case.minimum_distinct_artists is not None:
        route_status = "fail" if distinct_artists < case.minimum_distinct_artists else "pass"
        route_summary = f"Expected at least {case.minimum_distinct_artists} distinct artists; observed {distinct_artists}."
    else:
        route_status = "not_observed"
        route_summary = "No benchmark-specific artist route obligation is defined."

    resolution_observed = resolved_candidates is not None
    resolved_keys = {
        (item.artist.casefold(), item.title.casefold())
        for item in (resolved_candidates or [])
    }
    resolved_count = sum(key in resolved_keys for key in keys)
    resolution_rate = (
        (resolved_count / len(selected)) if selected else 1.0
    ) if resolution_observed else None
    novelty_distribution: dict[str, int] = {}
    for item in selected:
        if item.novelty_distance is not None:
            value = item.novelty_distance.value
            novelty_distribution[value] = novelty_distribution.get(value, 0) + 1

    human_review = [
        HumanReviewDimension(dimension=dimension)
        for dimension in PHASE51_RUBRIC.dimensions
    ]
    return Phase51Evaluation(
        case_id=case.case_id,
        case_title=case.title,
        hard_checks=[
            HardCheckResult(
                name="exact_duplicate_tracks",
                status="fail" if duplicate_count else "pass",
                summary=f"Found {duplicate_count} duplicate track occurrence(s).",
            ),
            HardCheckResult(
                name="benchmark_route_obligation",
                status=route_status,
                summary=route_summary,
            ),
            HardCheckResult(
                name="route_connection_metadata",
                status="not_observed",
                summary="Typed route connections are introduced by the route-contract PR.",
            ),
            HardCheckResult(
                name="catalog_resolution",
                status=("pass" if resolution_rate == 1 else "fail")
                if resolution_observed
                else "not_observed",
                summary=(
                    "Resolution was not part of this review artifact."
                    if not resolution_observed
                    else f"Resolved {resolved_count} of {len(selected)} selected tracks."
                ),
            ),
        ],
        diagnostics=Phase51Diagnostics(
            proposed_candidate_count=len(fast_plan.next_candidates),
            selected_track_count=len(selected),
            resolved_track_count=resolved_count,
            unresolved_track_count=len(selected) - resolved_count if resolution_observed else 0,
            distinct_artist_count=distinct_artists,
            same_artist_run_length=run_length,
            duplicate_track_count=duplicate_count,
            resolution_rate=resolution_rate,
            novelty_distribution=novelty_distribution,
        ),
        human_review=human_review,
    )


def build_review_bundle(
    case: GuidedDiscoveryCase,
    fast_plan: FastStartPlan,
    skeleton: ProgramSkeleton | None,
    resolved_candidates: list[ResolvedTrackCandidate] | None = None,
) -> GuidedDiscoveryReview:
    """Convert typed pipeline output into a compact, human-reviewable artifact."""
    def review_candidate(
        candidate: TrackProposal | ResolvedTrackCandidate,
        *,
        narrative_role: NarrativeRole | None = None,
        scene_cluster_rationale: str | None = None,
        evidence_ids: list[str] | None = None,
    ) -> ReviewCandidate:
        return ReviewCandidate(
            artist=candidate.artist,
            title=candidate.title,
            similarity_dimensions=list(candidate.similarity_dimensions),
            reasons=list(candidate.reasons),
            novelty_distance=candidate.novelty_distance,
            narrative_role=narrative_role,
            evidence_ids=list(evidence_ids or candidate.evidence_ids),
            scene_cluster_rationale=scene_cluster_rationale,
            track_ref=(candidate.track_ref if isinstance(candidate, ResolvedTrackCandidate) else None),
            resolution_status=(
                "resolved" if isinstance(candidate, ResolvedTrackCandidate) else "unresolved"
            ),
        )

    candidates_by_key: dict[tuple[str, str], ReviewCandidate] = {}
    for candidate in fast_plan.next_candidates:
        key = (candidate.artist.lower(), candidate.title.lower())
        candidates_by_key.setdefault(
            key,
            review_candidate(candidate),
        )

    arc: list[ReviewCandidate] = []
    if skeleton:
        for chapter in skeleton.chapters:
            if chapter.track is None:
                # Narrative-only beats remain reviewable without pretending
                # that they are catalog-resolved candidates.
                arc.append(
                    ReviewCandidate(
                        artist="",
                        title="",
                        similarity_dimensions=[],
                        reasons=[chapter.reason],
                        novelty_distance=chapter.novelty_distance,
                        narrative_role=chapter.narrative_role,
                        evidence_ids=list(chapter.evidence_ids),
                        scene_cluster_rationale=chapter.reason,
                        resolution_status="unresolved",
                    )
                )
                continue
            chapter_review_candidate = review_candidate(
                chapter.track,
                narrative_role=chapter.narrative_role,
                evidence_ids=list(chapter.evidence_ids or chapter.track.evidence_ids),
                scene_cluster_rationale=chapter.reason,
            )
            arc.append(chapter_review_candidate)
            key = (chapter.track.artist.lower(), chapter.track.title.lower())
            existing = candidates_by_key.get(key)
            if existing is None or chapter_review_candidate.resolution_status == "resolved":
                candidates_by_key[key] = chapter_review_candidate

    for candidate in resolved_candidates or []:
        candidates_by_key[(candidate.artist.lower(), candidate.title.lower())] = review_candidate(
            candidate
        )

    return GuidedDiscoveryReview(
        case_id=case.case_id,
        case_title=case.title,
        taste_hypotheses=list(fast_plan.immediate_taste_hypotheses),
        candidates=list(candidates_by_key.values()),
        program_arc=arc,
        rubric=RUBRIC,
        human_review_questions=list(RUBRIC.human_review_questions),
    )
