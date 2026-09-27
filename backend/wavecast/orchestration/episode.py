from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from wavecast.models.episode import (
    EpisodeSeed,
    EpisodeState,
    GenerationMode,
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    PlayableEpisode,
    Segment,
    SegmentKind,
    SegmentState,
    utc_now,
)
from wavecast.providers import AudioProvider, MockAudioProvider
from wavecast.providers.errors import ProviderError
from wavecast.storage.episodes import (
    EpisodeConcurrencyError,
    EpisodeNotFoundError,
    EpisodeRepository,
)

from .generation import (
    DeterministicMockProgressiveGenerator,
    GeneratedChapter,
    ProgressiveChapterGenerator,
)
from .narration_enrichment import author_pending_narration
from .runtime import StagedProgressiveRuntime

SESSION_TTL = timedelta(seconds=30)
DEFAULT_BUFFER_CHAPTERS = 2
DEFAULT_BUFFER_AHEAD_SECONDS = 5 * 60


def _is_wavecast_owned_audio_url(value: str) -> bool:
    '''Accept only same-origin API paths at the materialized runtime boundary.'''
    parsed = urlsplit(value)
    return (
        value.startswith("/api/")
        and not parsed.scheme
        and not parsed.netloc
        and not parsed.path.startswith("//")
    )


class EpisodeRuntimeError(ValueError):
    """Raised when a caller requests a transition outside runtime guarantees."""


@dataclass(frozen=True)
class GenerationSnapshot:
    episode: LiveEpisode
    last_segment_id: str
    last_order: int
    structural_signature: tuple[tuple[str, int, str], ...]


class InMemoryEpisodeRepository:
    def __init__(self) -> None:
        self._episodes: dict[str, LiveEpisode] = {}
        self._episode_id_by_listener_seed: dict[tuple[str, str], str] = {}

    def save(self, episode: LiveEpisode) -> LiveEpisode:
        stored = self._episodes.get(episode.id)
        if stored is not None and episode.version != stored.version:
            raise EpisodeConcurrencyError(f"stale episode snapshot: {episode.id}")
        self._episodes[episode.id] = episode
        episode.version += 1
        self._episode_id_by_listener_seed[(episode.listener_id, episode.seed_id)] = episode.id
        return episode

    def touch_heartbeat(self, episode_id: str, at: datetime) -> LiveEpisode:
        episode = self.get(episode_id)
        episode.last_activity_at = at
        episode.last_heartbeat_at = at
        return episode

    def get(self, episode_id: str) -> LiveEpisode:
        try:
            return self._episodes[episode_id]
        except KeyError as error:
            raise EpisodeNotFoundError(episode_id) from error

    def find_by_listener_seed(self, listener_id: str, seed_id: str) -> LiveEpisode | None:
        episode_id = self._episode_id_by_listener_seed.get((listener_id, seed_id))
        return self._episodes.get(episode_id) if episode_id else None

    def find_by_user_seed(self, user_id: str, seed_id: str) -> LiveEpisode | None:
        return next((episode for episode in self._episodes.values()
                     if episode.owner_user_id == user_id and episode.seed_id == seed_id), None)

    def claim_user(self, episode_id: str, listener_id: str, user_id: str) -> bool:
        episode = self._episodes.get(episode_id)
        if episode is None or episode.listener_id != listener_id:
            return False
        if episode.owner_user_id not in {None, user_id}:
            return False
        episode.owner_user_id = user_id
        return True

    def owned_by_user(self, episode_id: str, user_id: str) -> bool:
        episode = self._episodes.get(episode_id)
        return episode is not None and episode.owner_user_id == user_id

    def all(self) -> list[LiveEpisode]:
        return list(self._episodes.values())


class EpisodeOrchestrator:
    """Deterministic owner of playback, lifecycle, frontiers, and generation bounds."""

    def __init__(
        self,
        repository: EpisodeRepository,
        now: Callable[[], datetime] = utc_now,
        audio_provider: AudioProvider | None = None,
        progressive_generator: ProgressiveChapterGenerator | None = None,
        progressive_runtime: StagedProgressiveRuntime | None = None,
    ) -> None:
        self.repository = repository
        self.now = now
        self.audio_provider = audio_provider or MockAudioProvider()
        self.progressive_generator = progressive_generator or DeterministicMockProgressiveGenerator(
            self.audio_provider
        )
        self.progressive_runtime = progressive_runtime

    def start(
        self, seed: EpisodeSeed, listener_id: str = "test-listener",
        owner_user_id: str | None = None,
    ) -> LiveEpisode:
        now = self.now()
        opening_source = self.audio_provider.music_source(seed.opening_track_ref)
        opening_duration_seconds = (
            seed.opening_track_duration_seconds or opening_source.duration_seconds
        )
        opening = MusicSegment(
            id="segment-opening",
            chapter_id="chapter-1",
            order=0,
            state=SegmentState.COMMITTED,
            planned_duration_seconds=opening_duration_seconds,
            actual_duration_seconds=opening_duration_seconds,
            track_ref=seed.opening_track_ref,
            audio_source_url=opening_source.source_url,
            title=seed.opening_track_title,
            artist=seed.opening_track_artist,
            committed_at=now,
        )
        episode = LiveEpisode(
            seed_id=seed.id,
            listener_id=listener_id,
            owner_user_id=owner_user_id,
            state=EpisodeState.STREAMING,
            title=seed.title,
            topic=seed.topic,
            program_estimated_duration_seconds=seed.estimated_duration_seconds,
            segments=[opening],
            current_segment_id=opening.id,
            last_activity_at=now,
            last_heartbeat_at=now,
        )
        return self.repository.save(episode)

    def start_or_resume(
        self, seed: EpisodeSeed, listener_id: str = "test-listener",
        owner_user_id: str | None = None,
    ) -> LiveEpisode:
        if owner_user_id is not None:
            existing_user_episode = self.repository.find_by_user_seed(owner_user_id, seed.id)
            if existing_user_episode is not None:
                return self.resume(existing_user_episode.id)
        existing = self.repository.find_by_listener_seed(listener_id, seed.id)
        if existing is not None:
            if owner_user_id is not None and existing.owner_user_id is None:
                if self.repository.claim_user(existing.id, listener_id, owner_user_id):
                    existing.owner_user_id = owner_user_id
            return self.resume(existing.id)
        return self.start(seed, listener_id, owner_user_id)

    def import_materialized(
        self,
        *,
        seed_id: str,
        title: str,
        topic: str,
        estimated_duration_seconds: int,
        playable_episode: PlayableEpisode,
        listener_id: str = "test-listener",
        owner_user_id: str | None = None,
    ) -> LiveEpisode:
        """Persist a fully assembled episode through the normal runtime boundary."""
        if not playable_episode.segments:
            raise EpisodeRuntimeError("materialized episode must contain at least one segment")
        if any(not segment.audio_source_url for segment in playable_episode.segments):
            raise EpisodeRuntimeError("materialized episode contains a segment without audio")
        if any(
            not _is_wavecast_owned_audio_url(segment.audio_source_url or "")
            for segment in playable_episode.segments
        ):
            raise EpisodeRuntimeError(
                "materialized episode contains an external audio URL"
            )

        existing = (
            self.repository.find_by_user_seed(owner_user_id, seed_id)
            if owner_user_id is not None else None
        ) or self.repository.find_by_listener_seed(listener_id, seed_id)
        if existing is not None:
            if (
                owner_user_id is not None
                and existing.owner_user_id is None
                and self.repository.claim_user(existing.id, listener_id, owner_user_id)
            ):
                existing.owner_user_id = owner_user_id
            return self.resume(existing.id)

        now = self.now()
        segments = [
            segment.model_copy(
                update={
                    "state": (
                        SegmentState.COMMITTED
                        if index == 0
                        else SegmentState.AUDIO_READY
                    ),
                    "committed_at": now if index == 0 else None,
                }
            )
            for index, segment in enumerate(playable_episode.segments)
        ]
        episode = LiveEpisode(
            seed_id=seed_id,
            title=title,
            topic=topic,
            listener_id=listener_id,
            owner_user_id=owner_user_id,
            state=EpisodeState.MATERIALIZED,
            generation_mode=GenerationMode.FULL,
            program_estimated_duration_seconds=estimated_duration_seconds,
            segments=segments,
            current_segment_id=segments[0].id,
            last_activity_at=now,
            last_heartbeat_at=now,
        )
        return self.repository.save(episode)

    def get(self, episode_id: str, listener_id: str | None = None) -> LiveEpisode:
        try:
            episode = self.repository.get(episode_id)
        except EpisodeNotFoundError as error:
            raise EpisodeRuntimeError(f"episode not found: {episode_id}") from error
        if listener_id is not None and episode.listener_id != listener_id:
            raise EpisodeRuntimeError("episode does not belong to this listener")
        return episode

    def heartbeat(self, episode_id: str) -> LiveEpisode:
        self._active_episode(episode_id)
        return self.repository.touch_heartbeat(episode_id, self.now())

    def expire_stale_sessions(self) -> None:
        now = self.now()
        for episode in self.repository.all():
            if episode.is_listener_active and now - episode.last_heartbeat_at >= SESSION_TTL:
                episode.is_listener_active = False
                episode.is_playing = False
                episode.last_activity_at = now
                self.repository.save(episode)

    def capture_generation_snapshot(self, episode_id: str) -> GenerationSnapshot:
        episode = self.get(episode_id)
        if (
            not episode.is_listener_active
            and episode.generation_mode is not GenerationMode.FULL
        ):
            raise EpisodeRuntimeError("listener session is inactive; generation is progressive")
        segments = episode.ordered_segments
        if not segments:
            raise EpisodeRuntimeError("episode has no timeline segments")
        last = segments[-1]
        return GenerationSnapshot(
            episode=episode.model_copy(deep=True),
            last_segment_id=last.id,
            last_order=last.order,
            structural_signature=tuple(
                (segment.id, segment.order, segment.chapter_id)
                for segment in segments
            ),
        )

    def append_generated_chapter(
        self,
        episode_id: str,
        chapter: GeneratedChapter,
        snapshot: GenerationSnapshot,
    ) -> LiveEpisode:
        latest = self.get(episode_id)
        if (
            not latest.is_listener_active
            and latest.generation_mode is not GenerationMode.FULL
        ):
            raise EpisodeRuntimeError("listener session is inactive; discard progressive chapter")
        if latest.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}:
            raise EpisodeRuntimeError("episode is no longer progressively writable")
        current = latest.ordered_segments
        if not current or current[-1].id != snapshot.last_segment_id:
            raise EpisodeRuntimeError("generation anchor is stale")
        if current[-1].order != snapshot.last_order:
            raise EpisodeRuntimeError("generation anchor order is stale")
        current_signature = tuple(
            (segment.id, segment.order, segment.chapter_id) for segment in current
        )
        if current_signature != snapshot.structural_signature:
            raise EpisodeRuntimeError("generation anchor structure is stale")
        existing_ids = {segment.id for segment in latest.segments}
        existing_chapters = {segment.chapter_id for segment in latest.segments}
        if chapter.chapter_id in existing_chapters:
            raise EpisodeRuntimeError("generated chapter already exists")
        if any(segment.id in existing_ids for segment in chapter.segments):
            raise EpisodeRuntimeError("generated segment id already exists")
        if any(
            segment.kind is SegmentKind.MUSIC and not segment.is_audio_ready
            for segment in chapter.segments
        ):
            raise EpisodeRuntimeError("generated chapter contains unready music")
        if any(
            segment.kind is SegmentKind.NARRATION
            and segment.state
            not in {
                SegmentState.PLANNED,
                SegmentState.SCRIPT_READY,
                SegmentState.AUDIO_READY,
                SegmentState.SKIPPED,
            }
            for segment in chapter.segments
        ):
            raise EpisodeRuntimeError("generated chapter has invalid narration readiness")
        if any(segment.is_committed for segment in chapter.segments):
            raise EpisodeRuntimeError("generated chapter contains committed content")
        if any(segment.chapter_id != chapter.chapter_id for segment in chapter.segments):
            raise EpisodeRuntimeError("generated chapter has mixed chapter identities")

        first_order = current[-1].order + 1
        normalized = [
            segment.model_copy(update={"chapter_id": chapter.chapter_id, "order": first_order + index})
            for index, segment in enumerate(chapter.segments)
        ]
        latest.segments.extend(normalized)
        latest.last_activity_at = self.now()
        return self.repository.save(latest)

    def ensure_buffer(
        self,
        episode_id: str,
        *,
        target_chapters: int = DEFAULT_BUFFER_CHAPTERS,
        target_ahead_seconds: int = DEFAULT_BUFFER_AHEAD_SECONDS,
    ) -> LiveEpisode:
        return asyncio.run(
            self.ensure_buffer_async(
                episode_id,
                target_chapters=target_chapters,
                target_ahead_seconds=target_ahead_seconds,
            )
        )

    async def ensure_buffer_async(
        self,
        episode_id: str,
        *,
        target_chapters: int = DEFAULT_BUFFER_CHAPTERS,
        target_ahead_seconds: int = DEFAULT_BUFFER_AHEAD_SECONDS,
    ) -> LiveEpisode:
        """Bounded async generation behind the already-playable opening."""
        if target_chapters not in {1, 2}:
            raise EpisodeRuntimeError("target buffer must be one or two chapters")
        if target_ahead_seconds <= 0:
            raise EpisodeRuntimeError("target buffer seconds must be positive")
        episode = await asyncio.to_thread(self._active_episode, episode_id)
        if episode.state is EpisodeState.MATERIALIZED:
            return episode
        episode = await self._ensure_progressive_session(episode_id, episode)
        while True:
            partial_chapter_id = self._next_partial_chapter_id(episode)
            if partial_chapter_id is not None:
                self._materialize_chapter(episode, partial_chapter_id)
                episode = await asyncio.to_thread(self.repository.save, episode)
                continue
            ready_future_chapters = self._ready_future_chapter_count(episode)
            # The current music source is a latency budget, not a substitute for
            # a prepared successor. Even a five-minute opening must trigger at
            # least one future chapter before the queue can be considered healthy.
            if ready_future_chapters >= 1 and (
                ready_future_chapters >= target_chapters
                or episode.ready_audio_seconds_ahead >= target_ahead_seconds
            ):
                break
            next_chapter_id = self._next_future_chapter_id(episode)
            if next_chapter_id is not None:
                self._materialize_chapter(episode, next_chapter_id)
                episode = await asyncio.to_thread(self.repository.save, episode)
                continue
            snapshot = await asyncio.to_thread(
                self.capture_generation_snapshot, episode_id
            )
            episode, generator = await self._runtime_for_generation(episode_id, episode)
            chapter = await generator.generate_next(snapshot.episode)
            if chapter is None:
                break
            episode = await asyncio.to_thread(
                self.append_generated_chapter, episode_id, chapter, snapshot
            )
        episode = await asyncio.to_thread(self.repository.get, episode_id)
        self._start_ready_successor(episode)
        episode.last_activity_at = self.now()
        return await asyncio.to_thread(self.repository.save, episode)

    def tick(self, episode_id: str, *, elapsed_seconds: int) -> LiveEpisode:
        """Advance the logical player and start each contiguous ready segment automatically."""
        if elapsed_seconds < 0:
            raise EpisodeRuntimeError("elapsed playback time cannot be negative")
        episode = self._active_episode(episode_id)
        if not episode.is_playing:
            return episode
        remaining = elapsed_seconds
        while True:
            current = self._current_segment(episode)
            if current is None or not current.is_audio_ready:
                episode.is_playing = False
                break
            if current.state is SegmentState.AUDIO_READY:
                self._commit(episode, current)
            current_start = self._timeline_start(episode, current.id)
            played_in_current = max(0, episode.playback_position_seconds - current_start)
            seconds_to_end = current.duration_seconds - played_in_current
            if remaining < seconds_to_end:
                episode.playback_position_seconds += remaining
                break
            episode.playback_position_seconds = current_start + current.duration_seconds
            remaining -= seconds_to_end
            current.state = SegmentState.PLAYED
            current.played_at = self.now()
            next_segment = self._next_ready_after_optional_narration(
                episode, current.order
            )
            if next_segment is None:
                episode.is_playing = False
                break
            self._commit(episode, next_segment)
            if remaining == 0:
                break
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

    def complete_current_segment(self, episode_id: str) -> LiveEpisode:
        """Apply a browser ``ended`` event without running a server playback clock."""
        episode = self._active_episode(episode_id)
        current = self._current_segment(episode)
        if current is None:
            raise EpisodeRuntimeError("episode has no current segment")
        if not current.is_audio_ready:
            raise EpisodeRuntimeError("cannot complete audio that is not ready")
        if current.state is SegmentState.AUDIO_READY:
            self._commit(episode, current)
        episode.playback_position_seconds = (
            self._timeline_start(episode, current.id) + current.duration_seconds
        )
        current.state = SegmentState.PLAYED
        current.played_at = self.now()
        next_segment = self._next_ready_after_optional_narration(
            episode, current.order
        )
        if next_segment is None:
            episode.is_playing = False
        else:
            self._commit(episode, next_segment)
            episode.playback_position_seconds = self._timeline_start(episode, next_segment.id)
            episode.is_playing = True
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

    def seek(self, episode_id: str, position_seconds: int) -> LiveEpisode:
        episode = self._active_episode(episode_id)
        if position_seconds < 0 or position_seconds > episode.generated_frontier_seconds:
            raise EpisodeRuntimeError("cannot seek beyond the generated frontier")
        target = self._segment_at_position(episode, position_seconds)
        if target is not None:
            self._commit(episode, target)
        episode.playback_position_seconds = position_seconds
        episode.is_playing = target is not None
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

    def checkpoint_playback(self, episode_id: str, position_seconds: int) -> LiveEpisode:
        """Persist browser-owned progress without changing the current lifecycle segment."""
        episode = self._active_episode(episode_id)
        current = self._current_segment(episode)
        if (
            current is None
            or position_seconds < 0
            or position_seconds > episode.generated_frontier_seconds
        ):
            raise EpisodeRuntimeError("playback checkpoint is outside the generated timeline")
        start = self._timeline_start(episode, current.id)
        if not start <= position_seconds <= start + current.duration_seconds:
            raise EpisodeRuntimeError("playback checkpoint must remain in the current segment")
        episode.playback_position_seconds = position_seconds
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

    def commit_segment(self, episode_id: str, segment_id: str) -> LiveEpisode:
        """Explicit player-start seam retained for callers that have a selected segment."""
        episode = self._active_episode(episode_id)
        segment = episode.segment(segment_id)
        self._commit(episode, segment)
        episode.playback_position_seconds = self._timeline_start(episode, segment.id)
        episode.is_playing = True
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

    def next_playable(self, episode_id: str) -> LiveEpisode:
        """Remove unready narration before starting the next contiguous track."""
        episode = self._active_episode(episode_id)
        current = self._current_segment(episode)
        if current is None:
            raise EpisodeRuntimeError("episode has no current segment")
        next_segment = self._next_active_segment(episode, current.order)
        while (
            next_segment
            and next_segment.kind is SegmentKind.NARRATION
            and not next_segment.is_audio_ready
        ):
            next_segment.state = SegmentState.SKIPPED
            next_segment = self._next_active_segment(episode, current.order)
        if next_segment is None:
            raise EpisodeRuntimeError("no future playable segment exists")
        if not next_segment.is_audio_ready:
            self._make_ready(next_segment)
        self._commit(episode, next_segment)
        episode.playback_position_seconds = self._timeline_start(episode, next_segment.id)
        episode.is_playing = True
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

    def leave(self, episode_id: str) -> LiveEpisode:
        episode = self.get(episode_id)
        episode.is_listener_active = False
        episode.is_playing = False
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

    def pause(self, episode_id: str) -> LiveEpisode:
        episode = self._active_episode(episode_id)
        episode.is_playing = False
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

    def resume(self, episode_id: str) -> LiveEpisode:
        episode = self.get(episode_id)
        episode.is_listener_active = True
        episode.is_playing = self._current_segment(episode) is not None
        self._start_ready_successor(episode)
        if episode.state is not EpisodeState.MATERIALIZED:
            episode.state = EpisodeState.STREAMING
        episode.last_activity_at = self.now()
        episode.last_heartbeat_at = episode.last_activity_at
        return self.repository.save(episode)

    def request_full_generation(self, episode_id: str) -> LiveEpisode:
        """Upgrade one existing Episode to durable full-generation mode."""
        episode = self.get(episode_id)
        if episode.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}:
            return episode
        episode.generation_mode = GenerationMode.FULL
        episode.state = EpisodeState.MATERIALIZING
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

    def abort_full_generation(self, episode_id: str) -> LiveEpisode:
        """Return a failed FULL request to progressive listening without rewriting history."""
        episode = self.get(episode_id)
        if episode.state is EpisodeState.MATERIALIZING:
            episode.state = EpisodeState.STREAMING
            episode.generation_mode = GenerationMode.PROGRESSIVE
            episode.last_activity_at = self.now()
            return self.repository.save(episode)
        return episode

    async def author_pending_narration_async(
        self,
        episode_id: str,
        *,
        max_chapters: int = 2,
    ) -> LiveEpisode:
        """Run optional Writer enrichment after playable music is durable."""
        return await author_pending_narration(
            self,
            episode_id,
            max_chapters=max_chapters,
        )

    async def materialize_pending_narration_async(
        self,
        episode_id: str,
        *,
        max_segments: int = 2,
    ) -> LiveEpisode:
        """Best-effort TTS enrichment after music continuity is already durable."""
        if max_segments < 1:
            raise EpisodeRuntimeError("narration materialization limit must be positive")
        runtime = self.progressive_runtime
        materialize = getattr(runtime, "materialize_narration", None)
        if runtime is None or not callable(materialize):
            return await asyncio.to_thread(self.repository.get, episode_id)

        processed = 0
        while processed < max_segments:
            episode = await asyncio.to_thread(self.repository.get, episode_id)
            if (
                not episode.is_listener_active
                and episode.generation_mode is not GenerationMode.FULL
            ):
                break
            candidate = next(
                (
                    segment
                    for segment in episode.timeline_segments
                    if isinstance(segment, NarrationSegment)
                    and segment.state is SegmentState.SCRIPT_READY
                    and not segment.is_committed
                ),
                None,
            )
            if candidate is None:
                break
            candidate_id = candidate.id
            detached = candidate.model_copy(deep=True)
            try:
                materialized = await materialize(detached)
            except ProviderError:
                await asyncio.to_thread(
                    self._finish_narration_enrichment,
                    episode_id,
                    candidate_id,
                    None,
                )
            else:
                await asyncio.to_thread(
                    self._finish_narration_enrichment,
                    episode_id,
                    candidate_id,
                    materialized,
                )
            processed += 1
        return await asyncio.to_thread(self.repository.get, episode_id)

    def _finish_narration_enrichment(
        self,
        episode_id: str,
        segment_id: str,
        materialized: NarrationSegment | None,
    ) -> LiveEpisode:
        """Attach one finished asset, or skip failed speculative narration safely."""
        for attempt in range(2):
            episode = self.repository.get(episode_id)
            if (
                not episode.is_listener_active
                and episode.generation_mode is not GenerationMode.FULL
            ):
                return episode
            try:
                segment = episode.segment(segment_id)
            except KeyError:
                return episode
            if not isinstance(segment, NarrationSegment):
                return episode
            if segment.is_committed or segment.state is not SegmentState.SCRIPT_READY:
                return episode

            if materialized is None:
                segment.state = SegmentState.SKIPPED
            else:
                segment.asset_ref = materialized.asset_ref
                segment.audio_source_url = materialized.audio_source_url
                segment.actual_duration_seconds = materialized.actual_duration_seconds
                segment.state = SegmentState.AUDIO_READY
            episode.last_activity_at = self.now()
            try:
                return self.repository.save(episode)
            except EpisodeConcurrencyError:
                if attempt == 0:
                    continue
                raise
        return self.repository.get(episode_id)

    def materialize_all(self, episode_id: str) -> LiveEpisode:
        return asyncio.run(self.materialize_all_async(episode_id))

    async def materialize_all_async(self, episode_id: str) -> LiveEpisode:
        """Drain the same durable Episode even when no listener is currently active."""
        episode = await asyncio.to_thread(self.get, episode_id)
        if episode.state is EpisodeState.MATERIALIZED:
            return episode
        episode.generation_mode = GenerationMode.FULL
        episode.state = EpisodeState.MATERIALIZING
        episode = await asyncio.to_thread(self.repository.save, episode)
        episode = await self._ensure_progressive_session(episode_id, episode)
        while True:
            partial_chapter_id = self._next_partial_chapter_id(episode)
            if partial_chapter_id is not None:
                self._materialize_chapter(episode, partial_chapter_id)
                episode = await asyncio.to_thread(self.repository.save, episode)
                continue
            next_chapter_id = self._next_future_chapter_id(episode)
            if next_chapter_id is not None:
                self._materialize_chapter(episode, next_chapter_id)
                episode = await asyncio.to_thread(self.repository.save, episode)
                continue
            snapshot = await asyncio.to_thread(
                self.capture_generation_snapshot, episode_id
            )
            episode, generator = await self._runtime_for_generation(episode_id, episode)
            chapter = await generator.generate_next(snapshot.episode)
            if chapter is None:
                break
            episode = await asyncio.to_thread(
                self.append_generated_chapter, episode_id, chapter, snapshot
            )
        await self.author_pending_narration_async(
            episode_id,
            max_chapters=64,
        )
        await self.materialize_pending_narration_async(
            episode_id,
            max_segments=64,
        )
        episode = await asyncio.to_thread(self.repository.get, episode_id)
        for segment in episode.timeline_segments:
            if segment.is_audio_ready:
                continue
            if segment.kind is SegmentKind.NARRATION:
                segment.state = SegmentState.SKIPPED
                continue
            self._make_ready(segment)
        episode.state = EpisodeState.MATERIALIZED
        episode.generation_mode = GenerationMode.FULL
        episode.last_activity_at = self.now()
        return await asyncio.to_thread(self.repository.save, episode)

    def prepare_materialization(self, episode_id: str) -> LiveEpisode:
        """Prepare a full timeline while leaving narration network I/O external.

        The API/materialization service can then await TTS for narration segments and
        commit the final ``MATERIALIZED`` state. Existing synchronous callers keep
        using ``materialize_all`` and the deterministic mock AudioProvider path.
        """
        episode = self._active_episode(episode_id)
        episode.generation_mode = GenerationMode.FULL
        episode.state = EpisodeState.MATERIALIZING
        for segment in episode.timeline_segments:
            if segment.kind is SegmentKind.MUSIC and not segment.is_audio_ready:
                self._make_ready(segment)
            elif (
                segment.kind is SegmentKind.NARRATION
                and not segment.is_audio_ready
            ):
                if not isinstance(segment, NarrationSegment) or not segment.narration_text:
                    raise EpisodeRuntimeError("narration segment has no script text")
                segment.state = SegmentState.SCRIPT_READY
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

    def replace_speculative_music(self, episode_id: str, replacement_title: str) -> LiveEpisode:
        """A bounded replan seam: committed content is never changed."""
        episode = self._active_episode(episode_id)
        candidate = next(
            (
                item
                for item in episode.timeline_segments
                if item.kind is SegmentKind.MUSIC
                and not item.is_committed
                and item.state is SegmentState.PLANNED
            ),
            None,
        )
        if candidate is not None:
            candidate.title = replacement_title
            candidate.track_ref = f"mock:replanned:{candidate.order}"
            source = self.audio_provider.music_source(candidate.track_ref)
            candidate.audio_source_url = source.source_url
            candidate.actual_duration_seconds = None
        return self.repository.save(episode)

    async def _ensure_progressive_session(
        self, episode_id: str, episode: LiveEpisode
    ) -> LiveEpisode:
        if self.progressive_runtime is None or episode.progressive_session is not None:
            return episode
        snapshot = await asyncio.to_thread(self.capture_generation_snapshot, episode_id)
        prepared = await self.progressive_runtime.prepare_session(snapshot.episode)
        latest = await asyncio.to_thread(self.repository.get, episode_id)
        if (
            not latest.is_listener_active
            and latest.generation_mode is not GenerationMode.FULL
        ):
            raise EpisodeRuntimeError("listener session is inactive; discard prepared session")
        if latest.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}:
            raise EpisodeRuntimeError("episode is no longer progressively writable")
        current_signature = tuple(
            (segment.id, segment.order, segment.chapter_id)
            for segment in latest.ordered_segments
        )
        if current_signature != snapshot.structural_signature:
            raise EpisodeRuntimeError("progressive session preparation anchor is stale")
        if latest.progressive_session is not None:
            return latest
        latest.progressive_session = prepared
        try:
            return await asyncio.to_thread(self.repository.save, latest)
        except EpisodeConcurrencyError:
            reloaded = await asyncio.to_thread(self.repository.get, episode_id)
            if reloaded.progressive_session is not None:
                return reloaded
            raise

    async def _runtime_for_generation(
        self, episode_id: str, episode: LiveEpisode
    ) -> tuple[LiveEpisode, ProgressiveChapterGenerator]:
        episode = await self._ensure_progressive_session(episode_id, episode)
        if self.progressive_runtime is None:
            return episode, self.progressive_generator
        if episode.progressive_session is None:
            raise EpisodeRuntimeError("staged runtime session was not persisted")
        return episode, self.progressive_runtime.create_generator(episode.progressive_session)

    def _active_episode(self, episode_id: str) -> LiveEpisode:
        self.expire_stale_sessions()
        episode = self.get(episode_id)
        if not episode.is_listener_active:
            raise EpisodeRuntimeError("listener session is inactive; resume it before generating")
        return episode

    def _make_ready(self, segment: Segment) -> None:
        if segment.kind is SegmentKind.NARRATION:
            if not isinstance(segment, NarrationSegment) or not segment.narration_text:
                raise EpisodeRuntimeError("narration segment has no script text")
            segment.state = SegmentState.SCRIPT_READY
            segment.state = SegmentState.AUDIO_GENERATING
            source = self.audio_provider.narration_source(
                segment.id,
                segment.narration_text,
                segment.planned_duration_seconds,
            )
            segment.asset_ref = source.source_url
            segment.audio_source_url = source.source_url
            segment.actual_duration_seconds = source.duration_seconds
        elif segment.audio_source_url is None and segment.track_ref is not None:
            source = self.audio_provider.music_source(segment.track_ref)
            segment.audio_source_url = source.source_url
            segment.actual_duration_seconds = source.duration_seconds
        else:
            segment.actual_duration_seconds = (
                segment.actual_duration_seconds or segment.planned_duration_seconds
            )
        segment.state = SegmentState.AUDIO_READY

    def _commit(self, episode: LiveEpisode, segment: Segment) -> None:
        if not segment.is_audio_ready:
            raise EpisodeRuntimeError("cannot commit audio that is not ready")
        if segment.state is SegmentState.AUDIO_READY:
            segment.state = SegmentState.COMMITTED
            segment.committed_at = self.now()
        episode.current_segment_id = segment.id

    def _start_ready_successor(self, episode: LiveEpisode) -> None:
        current = self._current_segment(episode)
        if current is None or current.state is not SegmentState.PLAYED:
            return
        next_segment = self._next_ready_after_optional_narration(
            episode, current.order
        )
        if next_segment is None:
            episode.is_playing = False
            return
        self._commit(episode, next_segment)
        episode.playback_position_seconds = self._timeline_start(episode, next_segment.id)
        episode.is_playing = True

    @staticmethod
    def _next_ready_after_optional_narration(
        episode: LiveEpisode, order: int
    ) -> Segment | None:
        """Find a ready successor, skipping narration only when audio can continue.

        Unfinished narration remains speculative while there is no ready source
        behind it. Once a later source is ready, the narration can be skipped
        without turning a recoverable generation delay into dead air.
        """
        skipped: list[Segment] = []
        for segment in episode.timeline_segments:
            if segment.order <= order:
                continue
            if segment.is_audio_ready:
                for optional in skipped:
                    optional.state = SegmentState.SKIPPED
                return segment
            if segment.kind is SegmentKind.NARRATION:
                skipped.append(segment)
                continue
            return None
        return None

    @staticmethod
    def _next_active_segment(episode: LiveEpisode, order: int) -> Segment | None:
        return next(
            (segment for segment in episode.timeline_segments if segment.order > order), None
        )

    @staticmethod
    def _current_segment(episode: LiveEpisode) -> Segment | None:
        return episode.segment(episode.current_segment_id) if episode.current_segment_id else None

    @staticmethod
    def _timeline_start(episode: LiveEpisode, segment_id: str) -> int:
        total = 0
        for segment in episode.timeline_segments:
            if segment.id == segment_id:
                return total
            total += segment.duration_seconds
        raise EpisodeRuntimeError(f"segment is not present in the active timeline: {segment_id}")

    @staticmethod
    def _segment_at_position(episode: LiveEpisode, position_seconds: int) -> Segment | None:
        start = 0
        for segment in episode.timeline_segments:
            end = start + segment.duration_seconds
            if start <= position_seconds < end:
                return segment
            start = end
        return None

    @staticmethod
    def _chapter_ready_for_continuity(segments: list[Segment]) -> bool:
        """A chapter is continuity-ready only when its music is playable."""
        music = [segment for segment in segments if segment.kind is SegmentKind.MUSIC]
        return bool(music) and all(segment.is_audio_ready for segment in music)

    @staticmethod
    def _ready_future_chapter_count(episode: LiveEpisode) -> int:
        current = EpisodeOrchestrator._current_segment(episode)
        if current is None:
            return 0
        chapter_ids: list[str] = []
        for segment in episode.timeline_segments:
            if segment.order > current.order and segment.chapter_id != current.chapter_id:
                if segment.chapter_id not in chapter_ids:
                    chapter_ids.append(segment.chapter_id)
        return sum(
            EpisodeOrchestrator._chapter_ready_for_continuity(
                [
                    segment
                    for segment in episode.timeline_segments
                    if segment.chapter_id == chapter_id
                ]
            )
            for chapter_id in chapter_ids
        )

    @staticmethod
    def _next_partial_chapter_id(episode: LiveEpisode) -> str | None:
        """Return only chapters whose music readiness still blocks continuity."""
        current = EpisodeOrchestrator._current_segment(episode)
        if current is None:
            return None
        chapter_ids: list[str] = []
        for segment in episode.timeline_segments:
            if segment.chapter_id == current.chapter_id or segment.order > current.order:
                if segment.chapter_id not in chapter_ids:
                    chapter_ids.append(segment.chapter_id)
        for chapter_id in chapter_ids:
            chapter_segments = [
                segment
                for segment in episode.timeline_segments
                if segment.chapter_id == chapter_id
            ]
            if any(
                segment.kind is SegmentKind.MUSIC and not segment.is_audio_ready
                for segment in chapter_segments
            ):
                return chapter_id
        return None

    @staticmethod
    def _next_future_chapter_id(episode: LiveEpisode) -> str | None:
        """Ignore narration-only readiness gaps while looking for missing music."""
        current = EpisodeOrchestrator._current_segment(episode)
        if current is None:
            return None
        chapter_ids: list[str] = []
        for segment in episode.timeline_segments:
            if segment.order <= current.order:
                continue
            if segment.chapter_id not in chapter_ids:
                chapter_ids.append(segment.chapter_id)
        for chapter_id in chapter_ids:
            chapter_segments = [
                segment
                for segment in episode.timeline_segments
                if segment.chapter_id == chapter_id
            ]
            if any(
                segment.kind is SegmentKind.MUSIC and not segment.is_audio_ready
                for segment in chapter_segments
            ):
                return chapter_id
        return None

    def _materialize_chapter(self, episode: LiveEpisode, chapter_id: str) -> None:
        """Materialize music only; narration readiness is owned by enrichment."""
        for segment in episode.timeline_segments:
            if (
                segment.chapter_id == chapter_id
                and segment.kind is SegmentKind.MUSIC
                and not segment.is_audio_ready
            ):
                self._make_ready(segment)
