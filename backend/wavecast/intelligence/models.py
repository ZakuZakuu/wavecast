"""Typed intelligence contracts; provider payloads are normalized before entering these models."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    model_validator,
)

from wavecast.language import OutputLanguage as OutputLanguage  # re-exported for callers


class NoveltyDistance(StrEnum):
    VERY_CLOSE = "very_close"
    CLOSE = "close"
    BRIDGE = "bridge"
    DISCOVERY = "discovery"
    SURPRISE = "surprise"


def resolve_output_language(requested: OutputLanguage | str, topic: str) -> OutputLanguage:
    """Resolve ``auto`` from the user topic, never from catalog metadata."""

    requested = OutputLanguage(requested)
    if requested is not OutputLanguage.AUTO:
        return requested
    if any("\u3040" <= character <= "\u30ff" for character in topic):
        return OutputLanguage.JA_JP
    if any("\u4e00" <= character <= "\u9fff" for character in topic):
        return OutputLanguage.ZH_CN
    return OutputLanguage.EN_US


class NarrativeRole(StrEnum):
    ANCHOR = "anchor"
    VALIDATION = "validation"
    BRIDGE = "bridge"
    CONTRAST = "contrast"
    DISCOVERY = "discovery"
    RESOLUTION = "resolution"


class EditorialRelationType(StrEnum):
    """Typed reasons for moving from one playable track to the next."""

    SHARED_RHYTHMIC_POCKET = "shared_rhythmic_pocket"
    SHARED_MELODIC_LANGUAGE = "shared_melodic_language"
    SHARED_VOCAL_APPROACH = "shared_vocal_approach"
    SHARED_PRODUCTION_TEXTURE = "shared_production_texture"
    SCENE_OR_LINEAGE = "scene_or_lineage"
    ARTIST_DEVELOPMENT = "artist_development"
    CONTRAST = "contrast"


class EditorialConnection(BaseModel):
    """A pre-resolution explanation between selected track-bearing chapters.

    This relation describes Curator selection order; assembly may clear it when
    catalog resolution changes the playable route.
    """

    model_config = ConfigDict(extra="forbid")

    relation_type: EditorialRelationType
    musical_dimensions: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)

class SearchIntent(StrEnum):
    """Operational routing intent for one bounded research query."""

    DISCOVERY = "discovery"
    RESEARCH = "research"
    EXACT = "exact"


class ResearchPlanMode(StrEnum):
    """Whether background research should adapt, or intentionally stop."""

    ADAPTIVE = "adaptive"
    NO_ADDITIONAL_RESEARCH = "no_additional_research"


class EvidenceSourceCategory(StrEnum):
    """Conservative provenance categories, not authority scores."""

    UNKNOWN = "unknown"
    REFERENCE = "reference"
    VIDEO = "video"
    NEWS = "news"
    COMMUNITY = "community"
    INSTITUTIONAL = "institutional"
    CATALOG = "catalog"


class ClaimType(StrEnum):
    """The epistemic role of a Writer/Curator statement."""

    FACT = "fact"
    CORRELATION = "correlation"
    CAUSAL = "causal"
    INTERPRETATION = "editorial_interpretation"
    UNCERTAINTY = "uncertainty"


class ClaimSupport(BaseModel):
    """A typed statement-to-evidence link owned by the application contract."""

    model_config = ConfigDict(extra="forbid")

    claim_type: ClaimType
    claim: str = Field(min_length=1, max_length=500)
    evidence_ids: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        min_length=1, max_length=8
    )


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
    research_mode: ResearchPlanMode = ResearchPlanMode.ADAPTIVE
    no_research_reason: str | None = Field(default=None, min_length=1, max_length=300)
    facets: list[ResearchFacet] = Field(default_factory=list, max_length=8)
    # The model accepts a small proposal pool; deterministic application code
    # enforces the stricter provider execution budget.
    background_queries: list[PlannedResearchQuery] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_research_mode(self) -> ResearchPlan:
        if self.research_mode is ResearchPlanMode.NO_ADDITIONAL_RESEARCH:
            if self.no_research_reason is None:
                raise ValueError(
                    "no_research_reason is required when research_mode disables research"
                )
            if self.background_queries:
                raise ValueError(
                    "no-additional-research plans cannot contain background queries"
                )
        elif self.no_research_reason is not None:
            raise ValueError(
                "no_research_reason is only valid for no-additional-research plans"
            )
        return self


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
    canonical_url: str = ""
    source_domain: str = ""
    source_category: EvidenceSourceCategory = EvidenceSourceCategory.UNKNOWN
    source_preference_rank: int | None = Field(default=None, ge=0)
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
    # Length of the file the catalog will play, when the lookup reported it.  Planning uses it
    # to fit a programme to its time budget; it is not part of the track's identity.
    duration_seconds: int | None = Field(default=None, ge=1, le=36000)


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
    tts_text: str | None = Field(default=None, min_length=1, max_length=4000)
    tts_cues: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    intended_duration_seconds: int = Field(ge=1, le=300)


class RadioScriptBlockKind(StrEnum):
    INTRO = "intro"
    TRACK_INTRO = "track_intro"
    TRANSITION = "transition"
    OUTRO = "outro"


class NarrationSlotPlacement(StrEnum):
    """A concrete adjacency location in the resolved playback sequence."""

    BEFORE_TRACK = "before_track"
    AFTER_TRACK = "after_track"
    AFTER_FINAL_TRACK = "after_final_track"


class NarrationSlotContext(BaseModel):
    """Typed context for one real narration slot in final playback order.

    A chapter may expose more than one slot (for example a track intro before
    its track and a transition after it).  Numeric playback placement remains
    application-owned; Writer receives only the slot's allowed block kinds and
    the exact adjacent resolved tracks.
    """

    slot_id: str = Field(default="legacy", min_length=1, max_length=120)
    chapter_index: int = Field(ge=0)
    placement: NarrationSlotPlacement = NarrationSlotPlacement.AFTER_TRACK
    allowed_block_kinds: list[RadioScriptBlockKind] = Field(
        default_factory=lambda: list(RadioScriptBlockKind), min_length=1, max_length=4
    )
    chapter_track: ResolvedTrack | None = None
    just_played_track: ResolvedTrack | None = None
    upcoming_track: ResolvedTrack | None = None
    is_opening: bool = False
    is_final: bool = False


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
    tts_text: str | None = Field(default=None, min_length=1, max_length=4000)
    duration_seconds: int = Field(
        ge=1,
        le=300,
        validation_alias=AliasChoices("duration_seconds", "intended_duration_seconds"),
    )
    tts_cues: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    claim_support: list[ClaimSupport] = Field(default_factory=list, max_length=8)
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
    track: TrackProposal | None = None
    track_alternates: list[TrackProposal] = Field(default_factory=list, max_length=2)
    connection_from_previous_track: EditorialConnection | None = None
    narrative_role: NarrativeRole
    reason: str = Field(min_length=1, max_length=500)
    novelty_distance: NoveltyDistance | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    claim_support: list[ClaimSupport] = Field(default_factory=list, max_length=8)
    narration_goal: str = Field(min_length=1, max_length=400)


class ResearchBundle(BaseModel):
    anchors: list[str]
    taste_hypotheses: list[TasteHypothesis]
    evidence: list[Evidence]
    candidates: list[TrackProposal]
    research_plan: ResearchPlan | None = None
    uncertainties: list[str] = Field(default_factory=list)


class ProgramSkeleton(BaseModel):
    thesis: str = Field(min_length=1, max_length=600)
    chapters: list[ChapterPlan] = Field(min_length=1, max_length=32)
    estimated_duration_seconds: int = Field(gt=0)


class FastStartPlan(BaseModel):
    anchor_understanding: list[str]
    immediate_taste_hypotheses: list[TasteHypothesis]
    next_candidates: list[TrackProposal]
    selected_next_track: TrackProposal | None = None
    first_narration: NarrationScript
    uncertainties: list[str] = Field(default_factory=list)
    research_plan: ResearchPlan = Field(default_factory=empty_research_plan)
    _research_plan_omitted: bool = PrivateAttr(default=True)

    def model_post_init(self, __context: object) -> None:
        self._research_plan_omitted = "research_plan" not in self.model_fields_set

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        copied = super().model_copy(update=update, deep=deep)
        if update is not None and "research_plan" in update:
            copied._research_plan_omitted = False
        return copied


class FastResearchInput(BaseModel):
    topic: str
    anchor_tracks: list[str] = Field(default_factory=list)
    anchor_artists: list[str] = Field(default_factory=list)
    desired_duration_seconds: int = Field(gt=0)
    listener_taste_context: str | None = None
    output_language: OutputLanguage = OutputLanguage.AUTO


class FastResearchResult(BaseModel):
    bundle: ResearchBundle
    elapsed_ms: int = Field(ge=0)
    queries: list[str] = Field(default_factory=list)
