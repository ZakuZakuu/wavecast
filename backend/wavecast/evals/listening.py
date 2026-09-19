"""Credential-free listening-evaluation artifacts for assembled episodes.

This module deliberately reports deterministic observations and review prompts.  It
does not decide whether a program is good; the listening dimensions remain human
reviewed in Phase 5.2.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, Field

from wavecast.intelligence.models import ProgramSkeleton, RadioScriptBlock
from wavecast.models.episode import PlayableEpisode, Segment, SegmentKind
from wavecast.timing import ProgramTimingSummary


class RouteSurvivalMetrics(BaseModel):
    """How much of the selected editorial route survived catalog resolution."""

    selected_track_count: int = Field(ge=0)
    resolved_track_count: int = Field(ge=0)
    unresolved_track_count: int = Field(ge=0)
    resolution_survival_rate: float = Field(ge=0, le=1)
    expected_transition_count: int = Field(ge=0)
    surviving_transition_count: int = Field(ge=0)
    lost_transition_count: int = Field(ge=0)


class DurationMetrics(BaseModel):
    """Planned versus materialized duration observations."""

    target_seconds: int = Field(gt=0)
    planned_seconds: int = Field(ge=0)
    materialized_seconds: int = Field(ge=0)
    absolute_error_seconds: int = Field(ge=0)
    relative_error: float
    planned_narration_seconds: int = Field(ge=0)
    materialized_narration_seconds: int = Field(ge=0)
    target_narration_ratio: float = Field(ge=0, le=1)
    materialized_narration_ratio: float = Field(ge=0, le=1)
    duration_target_feasible: bool


class PacingWindow(BaseModel):
    """One fixed-size timeline window used for local pacing review."""

    index: int = Field(ge=0)
    start_seconds: int = Field(ge=0)
    end_seconds: int = Field(gt=0)
    music_seconds: int = Field(ge=0)
    narration_seconds: int = Field(ge=0)
    narration_ratio: float = Field(ge=0, le=1)


class PacingMetrics(BaseModel):
    """Local pacing observations; no automatic quality verdict is implied."""

    window_seconds: int = Field(gt=0)
    windows: list[PacingWindow] = Field(default_factory=list)
    longest_uninterrupted_music_seconds: int = Field(ge=0)
    longest_narration_burst_seconds: int = Field(ge=0)
    narration_heaviest_window_index: int | None = Field(default=None, ge=0)


class WriterContinuityMetrics(BaseModel):
    """Deterministic Writer/timeline continuity checks for human follow-up."""

    writer_chapter_count: int = Field(ge=0)
    parsed_block_count: int = Field(ge=0)
    normalized_block_count: int = Field(ge=0)
    final_timeline_narration_segments: int = Field(ge=0)
    normalized_block_loss_count: int = Field(ge=0)
    unresolved_track_mention_count: int = Field(ge=0)


class ListeningEvaluation(BaseModel):
    """Phase 5.2A artifact combining deterministic metrics and review prompts."""

    schema_version: str = "phase52a.v1"
    route_survival: RouteSurvivalMetrics
    duration: DurationMetrics
    pacing: PacingMetrics
    writer_continuity: WriterContinuityMetrics
    human_review_required: bool = True
    review_questions: list[str] = Field(default_factory=list)


class WriterChapterLike(Protocol):
    chapter_index: int
    parsed_blocks: Sequence[RadioScriptBlock]
    normalized_blocks: Sequence[RadioScriptBlock]


REVIEW_QUESTIONS = [
    "Would I keep listening?",
    "Does this feel like a radio show rather than an AI playlist?",
    "Did I learn something musically meaningful?",
    "Did the host speak too much or too little?",
    "Did transitions make me want to hear the next song?",
    "Did any section feel repetitive or synthetic?",
    "Was the ending satisfying?",
]


def build_listening_evaluation(
    *,
    skeleton: ProgramSkeleton,
    resolved_chapter_indices: Sequence[int],
    unresolved_chapter_indices: Sequence[int],
    unresolved_track_references: Sequence[tuple[str, str]],
    episode: PlayableEpisode,
    timing_summary: ProgramTimingSummary,
    writer_chapters: Sequence[WriterChapterLike],
    window_seconds: int = 300,
) -> ListeningEvaluation:
    """Build a safe Phase 5.2A artifact from one assembled episode.

    Chapter indices are supplied by the deterministic assembly boundary so this
    evaluator never guesses whether a catalog result corresponds to a proposal.
    Raw narration text is used only for a count of unresolved-track mentions and
    is never stored in the artifact.
    """

    selected_indices = [chapter.index for chapter in skeleton.chapters if chapter.track is not None]
    unresolved = set(unresolved_chapter_indices)
    resolved = set(resolved_chapter_indices)
    selected_count = len(selected_indices)
    resolved_count = sum(index in resolved for index in selected_indices)
    unresolved_count = sum(index in unresolved for index in selected_indices)
    expected_transitions = max(0, selected_count - 1)
    surviving_transitions = sum(
        left in resolved and right in resolved
        for left, right in zip(selected_indices, selected_indices[1:], strict=False)
    )
    duration = _duration_metrics(timing_summary)
    pacing = _pacing_metrics(episode, window_seconds)
    parsed_blocks = sum(len(item.parsed_blocks) for item in writer_chapters)
    normalized_blocks = sum(len(item.normalized_blocks) for item in writer_chapters)
    narration_segments = sum(
        segment.kind is SegmentKind.NARRATION
        for segment in episode.segments
        if segment.is_timeline_active
    )
    mentioned = 0
    for chapter in writer_chapters:
        for block in chapter.parsed_blocks:
            mentioned += sum(
                _contains_track_reference(block.text, artist, title)
                for artist, title in unresolved_track_references
            )

    return ListeningEvaluation(
        route_survival=RouteSurvivalMetrics(
            selected_track_count=selected_count,
            resolved_track_count=resolved_count,
            unresolved_track_count=unresolved_count,
            resolution_survival_rate=(resolved_count / selected_count if selected_count else 1.0),
            expected_transition_count=expected_transitions,
            surviving_transition_count=surviving_transitions,
            lost_transition_count=expected_transitions - surviving_transitions,
        ),
        duration=duration,
        pacing=pacing,
        writer_continuity=WriterContinuityMetrics(
            writer_chapter_count=len(writer_chapters),
            parsed_block_count=parsed_blocks,
            normalized_block_count=normalized_blocks,
            final_timeline_narration_segments=narration_segments,
            normalized_block_loss_count=max(0, parsed_blocks - normalized_blocks),
            unresolved_track_mention_count=mentioned,
        ),
        review_questions=list(REVIEW_QUESTIONS),
    )


def _contains_track_reference(text: str, artist: str, title: str) -> bool:
    normalized_text = _normalize_for_track_matching(text)
    normalized_artist = _normalize_for_track_matching(artist)
    normalized_title = _normalize_for_track_matching(title)
    if not normalized_artist or not normalized_title:
        return False
    return normalized_artist in normalized_text and normalized_title in normalized_text


def _normalize_for_track_matching(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if not unicodedata.category(character).startswith("P") and not character.isspace()
    )


def _duration_metrics(summary: ProgramTimingSummary) -> DurationMetrics:
    error = summary.actual_total_seconds - summary.desired_total_seconds
    return DurationMetrics(
        target_seconds=summary.desired_total_seconds,
        planned_seconds=summary.planned_total_seconds,
        materialized_seconds=summary.actual_total_seconds,
        absolute_error_seconds=abs(error),
        relative_error=(
            error / summary.desired_total_seconds if summary.desired_total_seconds else 0.0
        ),
        planned_narration_seconds=summary.planned_narration_seconds,
        materialized_narration_seconds=summary.actual_narration_seconds,
        target_narration_ratio=summary.target_narration_ratio,
        materialized_narration_ratio=summary.actual_narration_ratio,
        duration_target_feasible=summary.duration_target_feasible,
    )


def _pacing_metrics(episode: PlayableEpisode, window_seconds: int) -> PacingMetrics:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    segments = [item for item in episode.segments if item.is_timeline_active]
    total_seconds = sum(item.duration_seconds for item in segments)
    windows: list[PacingWindow] = []
    for index, start in enumerate(range(0, total_seconds, window_seconds)):
        end = min(total_seconds, start + window_seconds)
        music = 0
        narration = 0
        cursor = 0
        for segment in segments:
            segment_start = cursor
            segment_end = cursor + segment.duration_seconds
            cursor = segment_end
            overlap = max(0, min(end, segment_end) - max(start, segment_start))
            if segment.kind is SegmentKind.MUSIC:
                music += overlap
            else:
                narration += overlap
        window_total = music + narration
        windows.append(
            PacingWindow(
                index=index,
                start_seconds=start,
                end_seconds=end,
                music_seconds=music,
                narration_seconds=narration,
                narration_ratio=narration / window_total if window_total else 0.0,
            )
        )

    longest_music = _longest_contiguous_duration(segments, SegmentKind.MUSIC)
    longest_narration = _longest_contiguous_duration(segments, SegmentKind.NARRATION)
    heaviest = max(
        windows,
        key=lambda item: (item.narration_ratio, -item.index),
        default=None,
    )
    return PacingMetrics(
        window_seconds=window_seconds,
        windows=windows,
        longest_uninterrupted_music_seconds=longest_music,
        longest_narration_burst_seconds=longest_narration,
        narration_heaviest_window_index=heaviest.index if heaviest else None,
    )


def _longest_contiguous_duration(segments: Sequence[Segment], kind: SegmentKind) -> int:
    longest = 0
    current = 0
    for segment in segments:
        if segment.kind is kind:
            current += segment.duration_seconds
            longest = max(longest, current)
        else:
            current = 0
    return longest
