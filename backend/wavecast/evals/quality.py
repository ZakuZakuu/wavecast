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
    TASTE_DEPTH = "TasteDepth"
    CANDIDATE_VALIDITY = "CandidateValidity"
    LOCAL_COHERENCE = "LocalCoherence"
    DISCOVERY_RADIUS = "DiscoveryRadius"
    NOVELTY_CALIBRATION = "NoveltyCalibration"
    NARRATIVE_ARC = "NarrativeArc"
    EVIDENCE_DISCIPLINE = "EvidenceDiscipline"


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
