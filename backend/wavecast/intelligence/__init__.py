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
    ProgramSkeleton,
    ResearchBundle,
    TasteHypothesis,
    TrackCandidate,
)
from .planning import PlanningSession
from .research import BackgroundResearchService, FastResearchService
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
    "NarrativeRole",
    "NoveltyDistance",
    "ProgramSkeleton",
    "PlanningSession",
    "ResearchBundle",
    "TasteHypothesis",
    "TraceEvent",
    "TrackCandidate",
    "WriterService",
]
