"""Bounded, provider-neutral progressive intelligence services."""

from .background import BackgroundIntelligencePipeline, BackgroundPipelineResult
from .curation import CuratorService
from .fast_start import FastPathCoordinator, FastPathResult, FastStartPlanner
from .models import (
    ChapterPlan,
    Evidence,
    FastResearchInput,
    FastResearchResult,
    FastStartPlan,
    NarrationScript,
    NarrativeRole,
    NoveltyDistance,
    PlannedResearchQuery,
    ProgramSkeleton,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResearchBundle,
    ResearchFacet,
    ResearchPlan,
    ResolvedTrack,
    ResolvedTrackCandidate,
    SearchIntent,
    TasteHypothesis,
    TrackCandidate,
    TrackProposal,
    UnresolvedTrackError,
)
from .planning import PlanningSession
from .research import BackgroundResearchService, FastResearchService
from .resolution import (
    music_segment_from_track,
    resolve_track_candidate,
    resolve_track_proposal,
    resolve_track_proposal_across_providers,
)
from .trace import GenerationTrace, TraceEvent
from .writer import WriterService

__all__ = [
    "ChapterPlan",
    "BackgroundIntelligencePipeline",
    "BackgroundPipelineResult",
    "BackgroundResearchService",
    "CuratorService",
    "Evidence",
    "FastResearchInput",
    "FastResearchResult",
    "FastPathCoordinator",
    "FastPathResult",
    "FastResearchService",
    "FastStartPlanner",
    "FastStartPlan",
    "GenerationTrace",
    "NarrationScript",
    "RadioScript",
    "RadioScriptBlock",
    "RadioScriptBlockKind",
    "NarrativeRole",
    "NoveltyDistance",
    "ProgramSkeleton",
    "PlanningSession",
    "ResearchBundle",
    "ResearchFacet",
    "ResearchPlan",
    "PlannedResearchQuery",
    "SearchIntent",
    "ResolvedTrack",
    "ResolvedTrackCandidate",
    "TasteHypothesis",
    "TraceEvent",
    "TrackProposal",
    "TrackCandidate",
    "UnresolvedTrackError",
    "WriterService",
    "music_segment_from_track",
    "resolve_track_proposal_across_providers",
    "resolve_track_candidate",
    "resolve_track_proposal",
]
