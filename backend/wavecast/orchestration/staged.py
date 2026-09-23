"""Serializable staged intelligence contracts for progressive assembly.

This module deliberately stops before runtime scheduling. It captures the
normalized intelligence needed by a later generate_next adapter without
retaining provider clients, ephemeral URLs, or process-local progress cursors.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from wavecast.intelligence.models import (
    ChapterPlan,
    FastStartPlan,
    NarrationSlotContext,
    OutputLanguage,
    ProgramSkeleton,
    ResearchBundle,
    ResolvedTrack,
)
from wavecast.models.episode import LiveEpisode
from wavecast.timing import ProgramTimingPlan


class ProgressiveSessionDiagnostic(BaseModel):
    """Safe diagnostic metadata retained in a staged session snapshot."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=120)
    chapter_index: int | None = Field(default=None, ge=0)
    detail: str = Field(min_length=1, max_length=300)


class ProgressiveAssemblyChapter(BaseModel):
    """One normalized route step that a future staged generator may materialize."""

    model_config = ConfigDict(extra="forbid")

    chapter_id: str = Field(min_length=1, max_length=120)
    chapter: ChapterPlan
    resolved_track: ResolvedTrack | None = None
    slot_contexts: list[NarrationSlotContext] = Field(default_factory=list)
    target_narration_seconds: int = Field(ge=1)


class ProgressiveAssemblySession(BaseModel):
    """Serializable intelligence state for one progressive assembly.

    The session is data, not a live object graph. next_chapter derives progress
    from the persisted LiveEpisode timeline and this snapshot's stable route
    identities; no mutable cursor in this object is authoritative.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    topic: str = Field(min_length=1, max_length=300)
    listener_taste_context: str | None = Field(default=None, max_length=1000)
    desired_duration_seconds: int = Field(gt=0)
    max_tracks: int = Field(ge=2, le=8)
    max_chapters: int = Field(ge=2, le=32)
    output_language: OutputLanguage
    opening_track_ref: str | None = Field(default=None, max_length=300)
    fast_plan: FastStartPlan
    research: ResearchBundle
    skeleton: ProgramSkeleton
    chapters: list[ProgressiveAssemblyChapter] = Field(min_length=1, max_length=32)
    timing_plan: ProgramTimingPlan
    diagnostics: list[ProgressiveSessionDiagnostic] = Field(default_factory=list, max_length=64)

    def next_chapter(self, episode: LiveEpisode) -> ProgressiveAssemblyChapter | None:
        """Return the first route step absent from the persisted episode timeline."""

        existing_chapters = {segment.chapter_id for segment in episode.segments}
        return next(
            (chapter for chapter in self.chapters if chapter.chapter_id not in existing_chapters),
            None,
        )
