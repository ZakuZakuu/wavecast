"""Best-effort narration authoring after continuity-critical music is durable."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from wavecast.models.episode import (
    GenerationMode,
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    SegmentState,
)
from wavecast.orchestration.generation import GeneratedChapter
from wavecast.orchestration.runtime import StagedProgressiveRuntime
from wavecast.storage.episodes import EpisodeConcurrencyError, EpisodeRepository


class NarrationAuthoringHost(Protocol):
    repository: EpisodeRepository
    progressive_runtime: StagedProgressiveRuntime | None
    now: Callable[[], datetime]


async def author_pending_narration(
    host: NarrationAuthoringHost,
    episode_id: str,
    *,
    max_chapters: int = 2,
) -> LiveEpisode:
    """Run Writer only for already-persisted, still-speculative music chapters."""
    if max_chapters < 1:
        raise ValueError("narration authoring limit must be positive")
    runtime = host.progressive_runtime
    if runtime is None:
        return await asyncio.to_thread(host.repository.get, episode_id)

    processed = 0
    while processed < max_chapters:
        episode = await asyncio.to_thread(host.repository.get, episode_id)
        session = episode.progressive_session
        if session is None:
            break
        chapter_id = _next_authoring_chapter_id(episode)
        if chapter_id is None:
            break

        chapter_segments = [
            segment
            for segment in episode.ordered_segments
            if segment.chapter_id == chapter_id
        ]
        session_chapter = next(
            item for item in session.chapters if item.chapter_id == chapter_id
        )
        exposed = (
            episode.current_segment_id in {segment.id for segment in chapter_segments}
            or any(segment.is_committed for segment in chapter_segments)
        )
        if (
            not episode.is_listener_active
            and episode.generation_mode is not GenerationMode.FULL
        ):
            break
        should_degrade = (
            exposed
            or not session_chapter.slot_contexts
            or session_chapter.resolved_track is None
        )

        generated: GeneratedChapter | None = None
        if not should_degrade:
            generated = await runtime.author_narration(
                episode.model_copy(deep=True),
                chapter_id,
            )

        await asyncio.to_thread(
            _finish_authoring,
            host,
            episode_id,
            chapter_id,
            generated,
        )
        processed += 1

    return await asyncio.to_thread(host.repository.get, episode_id)


def _next_authoring_chapter_id(episode: LiveEpisode) -> str | None:
    session = episode.progressive_session
    if session is None:
        return None
    authored = set(session.narration_authored_chapter_ids)
    persisted = {segment.chapter_id for segment in episode.ordered_segments}
    return next(
        (
            chapter.chapter_id
            for chapter in session.chapters
            if chapter.chapter_id in persisted and chapter.chapter_id not in authored
        ),
        None,
    )


def _finish_authoring(
    host: NarrationAuthoringHost,
    episode_id: str,
    chapter_id: str,
    generated: GeneratedChapter | None,
) -> LiveEpisode:
    """Insert SCRIPT_READY narration unless playback has exposed the chapter."""
    for attempt in range(2):
        episode = host.repository.get(episode_id).model_copy(deep=True)
        session = episode.progressive_session
        if session is None or chapter_id in session.narration_authored_chapter_ids:
            return episode

        existing = [
            segment
            for segment in episode.ordered_segments
            if segment.chapter_id == chapter_id
        ]
        if not existing:
            return episode

        first_order = min(segment.order for segment in existing)
        last_order = max(segment.order for segment in existing)
        exposed = (
            episode.current_segment_id in {segment.id for segment in existing}
            or any(segment.is_committed for segment in existing)
            or any(
                segment.order > last_order and segment.is_committed
                for segment in episode.timeline_segments
            )
        )

        replacement: list[MusicSegment | NarrationSegment] | None = None
        if generated is not None and not exposed:
            existing_music = [
                segment for segment in existing if isinstance(segment, MusicSegment)
            ]
            generated_music = [
                segment
                for segment in generated.segments
                if isinstance(segment, MusicSegment)
            ]
            if len(existing_music) != 1 or len(generated_music) != 1:
                raise ValueError("narration authoring must preserve exactly one music source")
            current_music = existing_music[0]
            proposed_music = generated_music[0]
            if (
                current_music.track_ref != proposed_music.track_ref
                or current_music.artist != proposed_music.artist
                or current_music.title != proposed_music.title
            ):
                raise ValueError("narration authoring changed music identity")

            replacement = []
            for segment in generated.segments:
                if isinstance(segment, MusicSegment):
                    replacement.append(
                        current_music.model_copy(update={"order": segment.order})
                    )
                else:
                    if segment.state is not SegmentState.SCRIPT_READY:
                        raise ValueError("authored narration must remain script-ready")
                    replacement.append(segment)

        if replacement is not None:
            delta = len(replacement) - len(existing)
            retained: list[MusicSegment | NarrationSegment] = []
            for segment in episode.segments:
                if segment.chapter_id == chapter_id:
                    continue
                if segment.order > last_order:
                    segment = segment.model_copy(update={"order": segment.order + delta})
                retained.append(segment)
            episode.segments = retained + replacement

        episode.progressive_session = session.model_copy(
            update={
                "narration_authored_chapter_ids": [
                    *session.narration_authored_chapter_ids,
                    chapter_id,
                ]
            }
        )
        episode.last_activity_at = host.now()
        try:
            return host.repository.save(episode)
        except EpisodeConcurrencyError:
            if attempt == 0:
                continue
            raise

    return host.repository.get(episode_id)
