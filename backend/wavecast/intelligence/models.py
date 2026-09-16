"""Typed intelligence contracts; provider payloads are normalized before entering these models."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


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


class SearchIntent(StrEnum):
    """Operational routing intent for one bounded research query."""

    DISCOVERY = "discovery"
    RESEARCH = "research"
    EXACT = "exact"


class ResearchFacet(BaseModel):
    """An open-ended question that explains why background research is needed."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=500)
    priority: int = Field(ge=0, le=100)
    source_preferences: list[str] = Field(default_factory=list, max_length=8)


class PlannedResearchQuery(BaseModel):
    """One bounded query proposed by FastStart for the background stage."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    intent: SearchIntent
    facet_ids: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(min_length=1, max_length=300)


class ResearchPlan(BaseModel):
    """Topic-adaptive research intent, independent from any provider payload."""

    model_config = ConfigDict(extra="forbid")

    central_question: str = Field(min_length=1, max_length=500)
    facets: list[ResearchFacet] = Field(default_factory=list, max_length=8)
    background_queries: list[PlannedResearchQuery] = Field(default_factory=list, max_length=3)


def empty_research_plan() -> ResearchPlan:
    """Safe schema default for older callers that construct FastStartPlan directly."""

    return ResearchPlan(
        central_question="What evidence best answers the listener's topic?",
        facets=[],
        background_queries=[],
    )


class Evidence(BaseModel):
    id: str
    claim_or_excerpt: str = Field(min_length=1, max_length=800)
    source_url: str
    source_provider: str
    confidence: float = Field(ge=0, le=1)
    query: str
    source_title: str = ""
    facet_ids: list[str] = Field(default_factory=list, max_length=8)
    search_intent: SearchIntent | None = None


class TasteHypothesis(BaseModel):
    dimension: str = Field(min_length=1, max_length=80)
    interpretation: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)


class UnresolvedTrackError(ValueError):
    """Raised when a proposal is used where a catalog identity is required."""


class TrackProposal(BaseModel):
    """An artist/title hypothesis that still needs catalog resolution."""

    model_config = ConfigDict(extra="forbid")

    artist: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    reasons: list[str] = Field(default_factory=list)
    similarity_dimensions: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    novelty_distance: NoveltyDistance = NoveltyDistance.CLOSE


class ResolvedTrack(BaseModel):
    """The minimal catalog identity required before a track can enter playback."""

    track_ref: str = Field(min_length=1, max_length=300)
    canonical_artist: str = Field(min_length=1, max_length=120)
    canonical_title: str = Field(min_length=1, max_length=160)


# Compatibility name for callers that still use the former proposal type.  It is
# deliberately an alias, so it cannot add catalog identity fields to LLM schemas.
TrackCandidate = TrackProposal


class ResolvedTrackCandidate(TrackProposal):
    """A proposal enriched with catalog identity by deterministic application code."""

    track_ref: str = Field(min_length=1, max_length=300)
    canonical_artist: str = Field(min_length=1, max_length=120)
    canonical_title: str = Field(min_length=1, max_length=160)

    @property
    def resolution_status(self) -> Literal["resolved"]:
        return "resolved"

    def resolved_track(self) -> ResolvedTrack:
        return ResolvedTrack(
            track_ref=self.track_ref,
            canonical_artist=self.canonical_artist,
            canonical_title=self.canonical_title,
        )


class NarrationScript(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    tts_cues: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    intended_duration_seconds: int = Field(ge=1, le=300)


class RadioScriptBlockKind(StrEnum):
    INTRO = "intro"
    TRACK_INTRO = "track_intro"
    TRANSITION = "transition"
    OUTRO = "outro"


class RadioScriptBlock(BaseModel):
    """One spoken block in a radio-style script, before TTS materialization.

    ``track_index`` is the zero-based playback anchor: ``TRACK_INTRO(i)`` is
    immediately before track ``i`` and ``TRANSITION(i)`` occupies the gap after
    track ``i`` and before track ``i + 1``.  An unindexed ``INTRO`` follows the
    opening music; unindexed transitions are a compatibility form assigned to
    available gaps in order.  ``OUTRO`` follows the final track.
    """

    kind: RadioScriptBlockKind
    text: str = Field(min_length=1, max_length=4000)
    duration_seconds: int = Field(
        ge=1,
        le=300,
        validation_alias=AliasChoices("duration_seconds", "intended_duration_seconds"),
    )
    tts_cues: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    track_index: int | None = Field(default=None, ge=0)

    @property
    def intended_duration_seconds(self) -> int:
        return self.duration_seconds


class RadioScript(BaseModel):
    """Structured showrunner output; no audio asset or catalog identity is embedded."""

    blocks: list[RadioScriptBlock] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    intended_duration_seconds: int = Field(default=1, ge=1, le=1800)

    @property
    def text(self) -> str:
        """Compatibility view for callers that rendered one narration paragraph."""
        return " ".join(block.text for block in self.blocks)

    @property
    def tts_cues(self) -> list[str]:
        return [cue for block in self.blocks for cue in block.tts_cues]

    @classmethod
    def from_blocks(
        cls,
        blocks: list[tuple[RadioScriptBlockKind, str, int]],
        *,
        intended_duration_seconds: int,
    ) -> RadioScript:
        return cls(
            blocks=[
                RadioScriptBlock(
                    kind=kind,
                    text=text,
                    duration_seconds=duration,
                )
                for kind, text, duration in blocks
            ],
            intended_duration_seconds=intended_duration_seconds,
        )


class ChapterPlan(BaseModel):
    index: int = Field(ge=0)
    track: TrackProposal
    narrative_role: NarrativeRole
    reason: str = Field(min_length=1, max_length=500)
    novelty_distance: NoveltyDistance
    evidence_ids: list[str] = Field(default_factory=list)
    narration_goal: str = Field(min_length=1, max_length=400)


class ResearchBundle(BaseModel):
    anchors: list[str]
    taste_hypotheses: list[TasteHypothesis]
    evidence: list[Evidence]
    candidates: list[TrackProposal]
    uncertainties: list[str] = Field(default_factory=list)


class ProgramSkeleton(BaseModel):
    thesis: str = Field(min_length=1, max_length=600)
    chapters: list[ChapterPlan]
    estimated_duration_seconds: int = Field(gt=0)


class FastStartPlan(BaseModel):
    anchor_understanding: list[str]
    immediate_taste_hypotheses: list[TasteHypothesis]
    next_candidates: list[TrackProposal]
    selected_next_track: TrackProposal | None = None
    first_narration: NarrationScript
    uncertainties: list[str] = Field(default_factory=list)
    research_plan: ResearchPlan = Field(default_factory=empty_research_plan)


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
