"""Best-effort narration authoring after continuity-critical music is durable."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from functools import partial
from typing import Protocol

from wavecast.hosting import backup_ready, delivered_discussions
from wavecast.models.episode import (
    GenerationMode,
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    SegmentState,
)
from wavecast.models.progressive import ProgressiveAssemblySession
from wavecast.orchestration.authoring_gate import authoring_gate, finish_save
from wavecast.orchestration.generation import GeneratedChapter
from wavecast.orchestration.runtime import StagedProgressiveRuntime
from wavecast.presentation import HostMode
from wavecast.storage.episodes import EpisodeConcurrencyError, EpisodeRepository

logger = logging.getLogger(__name__)


class NarrationAuthoringHost(Protocol):
    repository: EpisodeRepository
    progressive_runtime: StagedProgressiveRuntime | None
    now: Callable[[], datetime]


# (episode id, chapter id) of the chapters being authored right now in this process.
_AUTHORING_IN_FLIGHT: dict[tuple[str, str], asyncio.Future[None]] = {}


async def author_pending_narration(
    host: NarrationAuthoringHost,
    episode_id: str,
    *,
    max_chapters: int = 2,
    include_backup: bool = False,
) -> LiveEpisode:
    """Run Writer only for already-persisted, still-speculative music chapters."""
    if max_chapters < 1:
        raise ValueError("narration authoring limit must be positive")

    initial = await asyncio.to_thread(host.repository.get, episode_id)
    if initial.presentation_intent.host_mode is HostMode.NONE:
        session = initial.progressive_session
        if session is not None:
            persisted = {segment.chapter_id for segment in initial.ordered_segments}
            authored = list(session.narration_authored_chapter_ids)
            for chapter in session.chapters:
                if chapter.chapter_id in persisted and chapter.chapter_id not in authored:
                    authored.append(chapter.chapter_id)
            if authored != session.narration_authored_chapter_ids:
                initial.progressive_session = session.model_copy(
                    update={"narration_authored_chapter_ids": authored}
                )
                initial.last_activity_at = host.now()
                initial = await asyncio.to_thread(host.repository.save, initial)
        return initial

    runtime = host.progressive_runtime
    if runtime is None:
        return initial

    processed = 0
    while processed < max_chapters:
        episode = await asyncio.to_thread(host.repository.get, episode_id)
        session = episode.progressive_session
        if session is None:
            break
        chapter_id = _next_authoring_chapter_id(episode, include_backup=include_backup)
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
        unresolved_music_slot = (
            session_chapter.resolved_track is None
            and session_chapter.chapter.track is not None
        )
        # A SKIPPED host seam is a final editorial decision (continuity
        # deadline, exposure, earlier failure). Do not spend Writer/TTS on it.
        seam_skipped = _has_skipped_narration(chapter_segments)
        plan = session.discussion_plan
        backup_unneeded = bool(
            plan is not None
            and chapter_id == plan.backup_chapter_id
            and delivered_discussions(episode) >= plan.minimum
        )
        unplanned = bool(
            plan is not None
            and chapter_id not in plan.chapter_ids
            and chapter_id != plan.backup_chapter_id
            and chapter_id not in {session.chapters[0].chapter_id, session.chapters[-1].chapter_id}
        )
        should_degrade = (
            backup_unneeded
            or unplanned
            or exposed
            or seam_skipped
            or not session_chapter.slot_contexts
            or unresolved_music_slot
        )

        # The chapter stays protected until its result is saved (or the run fails or is cancelled), so a
        # second path cannot start it while the first one's result is still being written.
        held_key: tuple[str, str] | None = None
        try:
            generated: GeneratedChapter | None = None
            if should_degrade:
                if backup_unneeded or unplanned:
                    reason = "discussion_plan"
                elif exposed:
                    reason = "exposed"
                elif seam_skipped:
                    reason = "seam_skipped"
                elif not session_chapter.slot_contexts:
                    reason = "no_slots"
                else:
                    reason = "unresolved_music"
                logger.info(
                    "narration_authoring_degraded episode_id=%s chapter_id=%s reason=%s",
                    episode_id,
                    chapter_id,
                    reason,
                )
            else:
                key = (episode_id, chapter_id)
                if key in _AUTHORING_IN_FLIGHT:
                    # The generation job and the detached enrichment both author the next chapter;
                    # the one that got here first finishes it, the other must not write it again.
                    logger.info(
                        "narration_authoring_skipped episode_id=%s chapter_id=%s reason=in_flight",
                        episode_id,
                        chapter_id,
                    )
                    if episode.generation_mode is GenerationMode.FULL:
                        # A full render must join the existing Writer, including its save,
                        # before deciding that the remaining host seams can be closed.
                        await asyncio.shield(_AUTHORING_IN_FLIGHT[key])
                        continue
                    break
                _AUTHORING_IN_FLIGHT[key] = asyncio.get_running_loop().create_future()
                held_key = key
                # The state may have moved on while this run waited its turn: look again, inside the
                # protected range, before spending anything.
                latest = await asyncio.to_thread(host.repository.get, episode_id)
                if _next_authoring_chapter_id(latest, include_backup=include_backup) != chapter_id:
                    logger.info(
                        "narration_authoring_skipped episode_id=%s chapter_id=%s reason=already_authored",
                        episode_id,
                        chapter_id,
                    )
                    break
                try:
                    with authoring_gate(partial(_chapter_still_open, host, episode_id, chapter_id)):
                        generated = await runtime.author_narration(
                            episode.model_copy(deep=True),
                            chapter_id,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning(
                        "narration_authoring_degraded episode_id=%s chapter_id=%s "
                        "reason=writer_error error_type=%s",
                        episode_id,
                        chapter_id,
                        type(error).__name__,
                    )
                    generated = None
                if generated is None:
                    logger.info(
                        "narration_authoring_degraded episode_id=%s chapter_id=%s "
                        "reason=writer_degraded",
                        episode_id,
                        chapter_id,
                    )
                else:
                    narration_count = sum(
                        isinstance(segment, NarrationSegment)
                        for segment in generated.segments
                    )
                    logger.info(
                        "narration_authoring_generated episode_id=%s chapter_id=%s "
                        "narration_segments=%s",
                        episode_id,
                        chapter_id,
                        narration_count,
                    )

            try:
                await finish_save(
                    asyncio.to_thread(
                        _finish_authoring,
                        host,
                        episode_id,
                        chapter_id,
                        generated,
                    )
                )
            except ValueError as error:
                logger.warning(
                    "narration_authoring_degraded episode_id=%s chapter_id=%s "
                    "reason=validation_error error_type=%s",
                    episode_id,
                    chapter_id,
                    type(error).__name__,
                )
                await finish_save(
                    asyncio.to_thread(
                        _finish_authoring,
                        host,
                        episode_id,
                        chapter_id,
                        None,
                    )
                )
            processed += 1
        finally:
            if held_key is not None:
                done = _AUTHORING_IN_FLIGHT.pop(held_key)
                done.set_result(None)

    final = await asyncio.to_thread(host.repository.get, episode_id)
    await _settle_dialogue(runtime, final)
    return final


async def _settle_dialogue(runtime: StagedProgressiveRuntime, episode: LiveEpisode) -> None:
    """Return stories whose passage did not make it into the programme; best effort."""

    if any(key[0] == episode.id for key in _AUTHORING_IN_FLIGHT):
        return
    settle = getattr(runtime, "settle_dialogue", None)
    if not callable(settle):
        return
    try:
        await settle(episode.id, episode.segments)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - bookkeeping must never fail authoring
        logger.warning(
            "dialogue_settle_failed episode_id=%s error_type=%s", episode.id, type(error).__name__
        )


def _chapter_still_open(host: NarrationAuthoringHost, episode_id: str, chapter_id: str) -> bool:
    """Whether inserting narration into this chapter would still be allowed right now."""

    episode = host.repository.get(episode_id)
    session = episode.progressive_session
    if session is None or chapter_id in session.narration_authored_chapter_ids:
        return False
    if not episode.is_listener_active and episode.generation_mode is not GenerationMode.FULL:
        return False
    existing = [segment for segment in episode.segments if segment.chapter_id == chapter_id]
    if not existing:
        return False
    last_order = max(segment.order for segment in existing)
    exposed = (
        episode.current_segment_id in {segment.id for segment in existing}
        or any(segment.is_committed for segment in existing)
        or any(
            segment.order > last_order and segment.is_committed
            for segment in episode.timeline_segments
        )
    )
    return not (exposed or _has_skipped_narration(existing))


def _with_chapter_research(
    session: ProgressiveAssemblySession, chapter_id: str, generated: GeneratedChapter
) -> dict[str, object]:
    """Session fields after adding the research found for one chapter's track."""

    have = {item.id for item in session.research.evidence}
    added = [item for item in generated.research_evidence if item.id not in have]
    research = session.research.model_copy(
        update={"evidence": [*session.research.evidence, *added]}
    )
    chapters = []
    for item in session.chapters:
        if item.chapter_id == chapter_id:
            ids = list(item.chapter.evidence_ids)
            ids.extend(i for i in generated.research_evidence_ids if i not in ids)
            item = item.model_copy(
                update={"chapter": item.chapter.model_copy(update={"evidence_ids": ids})}
            )
        chapters.append(item)
    return {"research": research, "chapters": chapters}


def _has_skipped_narration(segments: Sequence[object]) -> bool:
    """Whether a chapter's host seam beside its music was already given up.

    Trackless chapters are excluded: their SKIPPED placeholder is only the
    initial "no song to anchor the talk" state and is restored when authored.
    """

    return any(isinstance(segment, MusicSegment) for segment in segments) and any(
        isinstance(segment, NarrationSegment) and segment.state is SegmentState.SKIPPED
        for segment in segments
    )


def _next_authoring_chapter_id(episode: LiveEpisode, *, include_backup: bool = False) -> str | None:
    session = episode.progressive_session
    if session is None:
        return None
    authored = set(session.narration_authored_chapter_ids)
    persisted = {segment.chapter_id for segment in episode.ordered_segments}
    backup = session.discussion_plan.backup_chapter_id if session.discussion_plan else None
    # Hold the closing behind the reserved seam too, so its context can include the backup.
    backup_index = next(
        (i for i, item in enumerate(session.chapters) if item.chapter_id == backup), None
    )
    return next(
        (
            chapter.chapter_id
            for index, chapter in enumerate(session.chapters)
            if chapter.chapter_id in persisted
            and chapter.chapter_id not in authored
            and (
                backup_index is None
                or backup in authored
                or index < backup_index
                or (include_backup and backup_ready(episode))
            )
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
    for attempt in range(5):
        episode = host.repository.get(episode_id).model_copy(deep=True)
        session = episode.progressive_session
        if session is None or chapter_id in session.narration_authored_chapter_ids:
            return episode

        existing: list[MusicSegment | NarrationSegment] = sorted(
            (
                segment
                for segment in episode.segments
                if segment.chapter_id == chapter_id
            ),
            key=lambda segment: segment.order,
        )
        if not existing:
            return episode

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
        if generated is None or exposed or _has_skipped_narration(existing):
            # A placeholder reserves the immutable render seam while Writer/TTS
            # are pending. Once authoring degrades, or playback wins the race,
            # persist that editorial decision as SKIPPED so music can continue
            # and the renderer may safely freeze through the gap.
            replacement = [
                (
                    segment.model_copy(update={"state": SegmentState.SKIPPED})
                    if isinstance(segment, NarrationSegment)
                    and not segment.is_audio_ready
                    and segment.state is not SegmentState.SKIPPED
                    else segment
                )
                for segment in existing
            ]
        else:
            existing_music = [
                segment for segment in existing if isinstance(segment, MusicSegment)
            ]
            generated_music = [
                segment
                for segment in generated.segments
                if isinstance(segment, MusicSegment)
            ]
            if (
                len(existing_music) != len(generated_music)
                or len(existing_music) > 1
            ):
                raise ValueError("narration authoring changed chapter music cardinality")
            current_music = existing_music[0] if existing_music else None
            proposed_music = generated_music[0] if generated_music else None
            if current_music is not None and proposed_music is not None and (
                current_music.track_ref != proposed_music.track_ref
                or current_music.artist != proposed_music.artist
                or current_music.title != proposed_music.title
            ):
                raise ValueError("narration authoring changed music identity")

            replacement = []
            for segment in generated.segments:
                if isinstance(segment, MusicSegment):
                    if current_music is None:
                        raise ValueError("narration authoring introduced unexpected music")
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

        session_update: dict[str, object] = {
            "narration_authored_chapter_ids": [
                *session.narration_authored_chapter_ids,
                chapter_id,
            ]
        }
        if generated is not None and replacement is not None and (
            generated.research_evidence or generated.research_evidence_ids
        ):
            session_update.update(_with_chapter_research(session, chapter_id, generated))
        episode.progressive_session = session.model_copy(update=session_update)
        episode.last_activity_at = host.now()
        try:
            return host.repository.save(episode)
        except EpisodeConcurrencyError:
            if attempt < 4:
                continue
            raise

    return host.repository.get(episode_id)
