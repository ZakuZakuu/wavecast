"""Typed intelligence contracts; provider payloads are normalized before entering these models."""

from enum import StrEnum

from pydantic import BaseModel, Field


class NoveltyDistance(StrEnum):
    VERY_CLOSE = "very_close"
    CLOSE = "close"
    BRIDGE = "bridge"
    DISCOVERY = "discovery"
    SURPRISE = "surprise"


class NarrativeRole(StrEnum):
    ANCHOR = "anchor"
    VALIDATION = "validation"
    BRIDGE = "bridge"
    CONTRAST = "contrast"
    DISCOVERY = "discovery"
    RESOLUTION = "resolution"


class Evidence(BaseModel):
    id: str
    claim_or_excerpt: str = Field(min_length=1, max_length=800)
    source_url: str
    source_provider: str
    confidence: float = Field(ge=0, le=1)
    query: str


class TasteHypothesis(BaseModel):
    dimension: str = Field(min_length=1, max_length=80)
    interpretation: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)


class TrackCandidate(BaseModel):
    artist: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    track_ref: str | None = None
    reasons: list[str] = Field(default_factory=list)
    similarity_dimensions: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    novelty_distance: NoveltyDistance = NoveltyDistance.CLOSE


class NarrationScript(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    tts_cues: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    intended_duration_seconds: int = Field(ge=1, le=300)


class ChapterPlan(BaseModel):
    index: int = Field(ge=0)
    track: TrackCandidate
    narrative_role: NarrativeRole
    reason: str = Field(min_length=1, max_length=500)
    novelty_distance: NoveltyDistance
    evidence_ids: list[str] = Field(default_factory=list)
    narration_goal: str = Field(min_length=1, max_length=400)


class ResearchBundle(BaseModel):
    anchors: list[str]
    taste_hypotheses: list[TasteHypothesis]
    evidence: list[Evidence]
    candidates: list[TrackCandidate]
    uncertainties: list[str] = Field(default_factory=list)


class ProgramSkeleton(BaseModel):
    thesis: str = Field(min_length=1, max_length=600)
    chapters: list[ChapterPlan]
    estimated_duration_seconds: int = Field(gt=0)


class FastStartPlan(BaseModel):
    anchor_understanding: list[str]
    immediate_taste_hypotheses: list[TasteHypothesis]
    next_candidates: list[TrackCandidate]
    selected_next_track: TrackCandidate | None = None
    first_narration: NarrationScript
    uncertainties: list[str] = Field(default_factory=list)


class FastResearchInput(BaseModel):
    topic: str
    anchor_tracks: list[str] = Field(default_factory=list)
    anchor_artists: list[str] = Field(default_factory=list)
    desired_duration_seconds: int = Field(gt=0)
    listener_taste_context: str | None = None


class FastResearchResult(BaseModel):
    bundle: ResearchBundle
    elapsed_ms: int = Field(ge=0)
    queries: list[str] = Field(default_factory=list)
