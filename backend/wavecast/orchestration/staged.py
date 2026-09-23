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
from wavecast.models.episode import LiveEpisode, Segment, SegmentKind
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


class ProgressiveSessionReconstructionError(ValueError):
    """Raised when persisted playback state is not a valid session prefix."""


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
        """Return the next route step after validating persisted progress.

        The persisted timeline is authoritative only when it is a contiguous
        prefix of this session's route. A chapter id by itself is not enough:
        stale or unrelated content must fail closed rather than silently
        advancing the session.
        """

        persisted_by_chapter: dict[str, list[Segment]] = {}
        persisted_order: list[str] = []
        for segment in episode.ordered_segments:
            if segment.chapter_id not in persisted_by_chapter:
                persisted_by_chapter[segment.chapter_id] = []
                persisted_order.append(segment.chapter_id)
            persisted_by_chapter[segment.chapter_id].append(segment)

        route_order = list(self.chapters)
        if persisted_order and persisted_order[0] == "chapter-1":
            opening_segments = persisted_by_chapter["chapter-1"]
            opening_music = [
                segment
                for segment in opening_segments
                if segment.kind is SegmentKind.MUSIC
            ]
            if self.opening_track_ref is not None and (
                len(opening_music) != 1
                or opening_music[0].track_ref != self.opening_track_ref
            ):
                raise ProgressiveSessionReconstructionError(
                    "persisted application opening does not match session identity"
                )
            persisted_order = persisted_order[1:]
        elif "chapter-1" in persisted_order:
            raise ProgressiveSessionReconstructionError(
                "persisted application opening is out of order"
            )

        if len(persisted_order) > len(route_order):
            raise ProgressiveSessionReconstructionError(
                "persisted route contains unknown future chapters"
            )

        for index, chapter_id in enumerate(persisted_order):
            expected = route_order[index]
            if chapter_id != expected.chapter_id:
                raise ProgressiveSessionReconstructionError(
                    "persisted route is not a contiguous session prefix"
                )
            chapter_segments = persisted_by_chapter[chapter_id]
            music_segments = [
                segment
                for segment in chapter_segments
                if segment.kind is SegmentKind.MUSIC
            ]
            if expected.resolved_track is None:
                continue
            if len(music_segments) != 1:
                raise ProgressiveSessionReconstructionError(
                    "persisted resolved chapter must contain one music segment"
                )
            persisted_track = music_segments[0]
            resolved_track = expected.resolved_track
            if (
                persisted_track.track_ref != resolved_track.track_ref
                or persisted_track.artist != resolved_track.canonical_artist
                or persisted_track.title != resolved_track.canonical_title
            ):
                raise ProgressiveSessionReconstructionError(
                    "persisted music identity does not match session route"
                )

        return (
            route_order[len(persisted_order)]
            if len(persisted_order) < len(route_order)
            else None
        )
