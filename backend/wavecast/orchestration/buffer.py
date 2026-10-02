"""Deterministic refill decisions; never a playback clock or seek boundary."""

from dataclasses import dataclass
from math import ceil

from wavecast.models.episode import EpisodeState, GenerationMode, LiveEpisode, SegmentKind


@dataclass(frozen=True)
class BufferDecision:
    needs_generation: bool
    urgent: bool
    target_seconds: int
    current_remaining_seconds: int


def buffer_decision(
    episode: LiveEpisode, *, baseline_seconds: int = 180, max_chapters: int = 2
) -> BufferDecision:
    if baseline_seconds <= 0:
        raise ValueError("buffer baseline must be positive")
    if max_chapters not in {1, 2}:
        raise ValueError("buffer must be one or two chapters")
    # A bounded latency estimate plus margin, not an LLM deadline. The chapter
    # cap remains enforced by the orchestrator even at the maximum target.
    target = max(baseline_seconds, min(600, ceil(episode.generation_latency_seconds * 1.5 + 30)))
    terminal = episode.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}
    if episode.program_transport_active:
        # Three minutes is the runway to preserve, not the instant to start
        # work. Include cold-start and observed generation + publication cost.
        latency = episode.generation_latency_seconds + episode.program_publication_latency_seconds
        target = min(600, baseline_seconds + max(120, ceil(latency * 1.5 + 30)))
        frontier = (
            episode.program_rendered_frontier_seconds
            if episode.program_rendered_frontier_seconds is not None
            else episode.generated_frontier_seconds
        )
        remaining = max(
            0,
            int(frontier - episode.program_playback_position_seconds),
        )
        needs = not terminal and (
            episode.generation_mode is GenerationMode.FULL
            or (episode.is_listener_active and remaining < target)
        )
        return BufferDecision(
            needs_generation=needs,
            urgent=needs and remaining < baseline_seconds,
            target_seconds=target,
            current_remaining_seconds=remaining,
        )

    remaining = 0
    offset = 0
    ready_chapters: set[str] = set()
    current_chapter: str | None = None
    seen_current = False
    for segment in episode.timeline_segments:
        if seen_current:
            if segment.kind is SegmentKind.MUSIC:
                if not segment.is_audio_ready:
                    break
                if segment.chapter_id != current_chapter:
                    ready_chapters.add(segment.chapter_id)
            continue
        if segment.id == episode.current_segment_id:
            seen_current = True
            current_chapter = segment.chapter_id
            if segment.is_audio_ready:
                remaining = max(
                    0, segment.duration_seconds - max(0, episode.playback_position_seconds - offset)
                )
            continue
        offset += segment.duration_seconds
    needs = not terminal and (
        episode.generation_mode is GenerationMode.FULL
        or (
            episode.is_listener_active
            and len(ready_chapters) < max_chapters
            and (not episode.has_ready_successor or episode.ready_audio_seconds_ahead < target)
        )
    )
    return BufferDecision(
        needs_generation=needs,
        urgent=needs and not episode.has_ready_successor and remaining <= 30,
        target_seconds=target,
        current_remaining_seconds=remaining,
    )
