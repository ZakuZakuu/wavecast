from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from wavecast.models.episode import (
    EpisodeSeed,
    EpisodeState,
    GenerationMode,
    LiveEpisode,
    Segment,
    SegmentKind,
    SegmentState,
    utc_now,
)

SESSION_TTL = timedelta(seconds=30)
DEFAULT_BUFFER_CHAPTERS = 2


class EpisodeRuntimeError(ValueError):
    """Raised when a caller requests a transition outside runtime guarantees."""


class InMemoryEpisodeRepository:
    def __init__(self) -> None:
        self._episodes: dict[str, LiveEpisode] = {}
        self._episode_id_by_seed: dict[str, str] = {}

    def save(self, episode: LiveEpisode) -> LiveEpisode:
        self._episodes[episode.id] = episode
        self._episode_id_by_seed[episode.seed_id] = episode.id
        return episode

    def get(self, episode_id: str) -> LiveEpisode:
        try:
            return self._episodes[episode_id]
        except KeyError as error:
            raise EpisodeRuntimeError(f"episode not found: {episode_id}") from error

    def find_by_seed(self, seed_id: str) -> LiveEpisode | None:
        episode_id = self._episode_id_by_seed.get(seed_id)
        return self._episodes.get(episode_id) if episode_id else None

    def all(self) -> list[LiveEpisode]:
        return list(self._episodes.values())


class EpisodeOrchestrator:
    """Deterministic owner of playback, lifecycle, frontiers, and generation bounds."""

    def __init__(
        self,
        repository: InMemoryEpisodeRepository,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.repository = repository
        self.now = now

    def start(self, seed: EpisodeSeed) -> LiveEpisode:
        now = self.now()
        opening = Segment(
            id="segment-opening",
            chapter_id="chapter-1",
            order=0,
            kind=SegmentKind.MUSIC,
            state=SegmentState.COMMITTED,
            planned_duration_seconds=22,
            actual_duration_seconds=22,
            track_ref=seed.opening_track_ref,
            title=seed.opening_track_title,
            artist=seed.opening_track_artist,
            committed_at=now,
        )
        episode = LiveEpisode(
            seed_id=seed.id,
            state=EpisodeState.STREAMING,
            program_estimated_duration_seconds=seed.estimated_duration_seconds,
            segments=[opening, *self._future_segments()],
            current_segment_id=opening.id,
            last_activity_at=now,
            last_heartbeat_at=now,
        )
        return self.repository.save(episode)

    def start_or_resume(self, seed: EpisodeSeed) -> LiveEpisode:
        existing = self.repository.find_by_seed(seed.id)
        return self.resume(existing.id) if existing else self.start(seed)

    def get(self, episode_id: str) -> LiveEpisode:
        return self.repository.get(episode_id)

    def heartbeat(self, episode_id: str) -> LiveEpisode:
        episode = self._active_episode(episode_id)
        episode.last_activity_at = self.now()
        episode.last_heartbeat_at = episode.last_activity_at
        return self.repository.save(episode)

    def expire_stale_sessions(self) -> None:
        now = self.now()
        for episode in self.repository.all():
            if episode.is_listener_active and now - episode.last_heartbeat_at >= SESSION_TTL:
                episode.is_listener_active = False
                episode.is_playing = False
                episode.last_activity_at = now
                self.repository.save(episode)

    def ensure_buffer(
        self,
        episode_id: str,
        *,
        target_chapters: int = DEFAULT_BUFFER_CHAPTERS,
    ) -> LiveEpisode:
        """Materialize only enough contiguous future chapters for safe playback."""
        if target_chapters not in {1, 2}:
            raise EpisodeRuntimeError("target buffer must be one or two chapters")
        episode = self._active_episode(episode_id)
        if episode.state is EpisodeState.MATERIALIZED:
            return episode
        while self._ready_future_chapter_count(episode) < target_chapters:
            next_segment = next(
                (segment for segment in episode.timeline_segments if not segment.is_audio_ready),
                None,
            )
            if next_segment is None:
                break
            self._make_ready(next_segment)
        self._start_ready_successor(episode)
        episode.last_activity_at = self.now()
        return self.repository.save(episode)

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
            next_segment = self._next_active_segment(episode, current.order)
            if next_segment is None or not next_segment.is_audio_ready:
                episode.is_playing = False
                break
            self._commit(episode, next_segment)
            if remaining == 0:
                break
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

    def materialize_all(self, episode_id: str) -> LiveEpisode:
        episode = self._active_episode(episode_id)
        episode.generation_mode = GenerationMode.FULL
        episode.state = EpisodeState.MATERIALIZING
        for segment in episode.timeline_segments:
            if not segment.is_audio_ready:
                self._make_ready(segment)
        episode.state = EpisodeState.MATERIALIZED
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
        return self.repository.save(episode)

    def _active_episode(self, episode_id: str) -> LiveEpisode:
        self.expire_stale_sessions()
        episode = self.get(episode_id)
        if not episode.is_listener_active:
            raise EpisodeRuntimeError("listener session is inactive; resume it before generating")
        return episode

    @staticmethod
    def _make_ready(segment: Segment) -> None:
        if segment.kind is SegmentKind.NARRATION:
            segment.state = SegmentState.SCRIPT_READY
            segment.narration_text = (
                segment.narration_text or "A short, evidence-aware transition into the next track."
            )
            segment.state = SegmentState.AUDIO_GENERATING
            segment.asset_ref = f"fake-tts://{segment.id}"
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
        next_segment = self._next_active_segment(episode, current.order)
        if next_segment is None or not next_segment.is_audio_ready:
            episode.is_playing = False
            return
        self._commit(episode, next_segment)
        episode.playback_position_seconds = self._timeline_start(episode, next_segment.id)
        episode.is_playing = True

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
            all(
                segment.is_audio_ready
                for segment in episode.timeline_segments
                if segment.chapter_id == chapter_id
            )
            for chapter_id in chapter_ids
        )

    @staticmethod
    def _future_segments() -> list[Segment]:
        return [
            Segment(
                id="segment-narration-1",
                chapter_id="chapter-2",
                order=1,
                kind=SegmentKind.NARRATION,
                planned_duration_seconds=10,
                title="Host introduction",
            ),
            Segment(
                id="segment-bridge",
                chapter_id="chapter-2",
                order=2,
                kind=SegmentKind.MUSIC,
                planned_duration_seconds=24,
                track_ref="mock:bridge",
                title="Midnight Transfer",
                artist="Signal Garden",
            ),
            Segment(
                id="segment-narration-2",
                chapter_id="chapter-3",
                order=3,
                kind=SegmentKind.NARRATION,
                planned_duration_seconds=11,
                title="Host connection",
            ),
            Segment(
                id="segment-resolution",
                chapter_id="chapter-3",
                order=4,
                kind=SegmentKind.MUSIC,
                planned_duration_seconds=26,
                track_ref="mock:resolution",
                title="Daybreak in Stereo",
                artist="Southbound FM",
            ),
            Segment(
                id="segment-narration-3",
                chapter_id="chapter-4",
                order=5,
                kind=SegmentKind.NARRATION,
                planned_duration_seconds=9,
                title="Host resolution",
            ),
            Segment(
                id="segment-finale",
                chapter_id="chapter-4",
                order=6,
                kind=SegmentKind.MUSIC,
                planned_duration_seconds=25,
                track_ref="mock:finale",
                title="Afterimage Avenue",
                artist="Southbound FM",
            ),
        ]
