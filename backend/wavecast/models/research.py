from datetime import UTC, datetime

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    id: str
    claim: str
    source_url: str
    source_title: str
    provider: str
    confidence: float = Field(ge=0, le=1)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TrackCandidate(BaseModel):
    canonical_track_ref: str
    artist: str
    title: str
    reasons: list[str]
    evidence_ids: list[str]
    novelty_distance: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    available: bool


class ResearchBundle(BaseModel):
    id: str
    taste_hypotheses: list[str]
    evidence: list[Evidence]
    candidates: list[TrackCandidate]
    open_questions: list[str]
    research_cost_estimate: float = Field(ge=0)
