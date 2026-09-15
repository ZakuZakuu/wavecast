"""Typed, bounded provider-quality probe contracts; not a production agent pipeline."""

from pydantic import BaseModel, Field


class ProbeCandidateTrack(BaseModel):
    artist: str
    track: str
    why_it_may_fit: str
    similarity_dimensions: list[str] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ResearchProbeReport(BaseModel):
    anchor_understanding: list[str]
    taste_hypotheses: list[str]
    candidate_tracks: list[ProbeCandidateTrack]
    candidate_artists: list[str]
    evidence_based_observations: list[str]
    uncertainties: list[str]
