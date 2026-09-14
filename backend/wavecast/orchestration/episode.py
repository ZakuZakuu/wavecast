from __future__ import annotations

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


class EpisodeRuntimeError(ValueError):
    """Raised when a caller requests a transition outside runtime guarantees."""


class InMemoryEpisodeRepository:
    def __init__(self) -> None:
        self._episodes: dict[str, LiveEpisode] = {}

    def save(self, episode: LiveEpisode) -> LiveEpisode:
        self._episodes[episode.id] = episode
        return episode

    def get(self, episode_id: str) -> LiveEpisode:
        try:
            return self._episodes[episode_id]
        except KeyError as error:
            raise EpisodeRuntimeError(f"episode not found: {episode_id}") from error


class EpisodeOrchestrator:
    """Deterministic owner of episode state and frontier transitions.

    AI/provider adapters may propose content later, but only this runtime mutates lifecycle,
    activity, commitments, and materialization state.
    """

    def __init__(self, repository: InMemoryEpisodeRepository) -> None:
        self.repository = repository

    def start(self, seed: EpisodeSeed) -> LiveEpisode:
        opening = Segment(
            id="segment-opening",
            chapter_id="chapter-1",
            order=0,
            kind=SegmentKind.MUSIC,
            state=SegmentState.AUDIO_READY,
            planned_duration_seconds=22,
            actual_duration_seconds=22,
            track_ref=seed.opening_track_ref,
            title=seed.opening_track_title,
            artist=seed.opening_track_artist,
        )
        episode = LiveEpisode(
            seed_id=seed.id,
            state=EpisodeState.STREAMING,
            segments=[opening, *self._future_segments()],
            current_segment_id=opening.id,
        )
        return self.repository.save(episode)

    def get(self, episode_id: str) -> LiveEpisode:
        return self.repository.get(episode_id)

    def advance(self, episode_id: str) -> LiveEpisode:
        """Materialize exactly one next segment while active, bounded by caller polling."""
        episode = self.get(episode_id)
        if not episode.is_listener_active or episode.state is EpisodeState.MATERIALIZED:
            return episode
        next_segment = next((item for item in episode.ordered_segments if not item.is_audio_ready), None)
        if next_segment is None:
            episode.state = EpisodeState.MATERIALIZED
            return self.repository.save(episode)
        self._make_ready(next_segment)
        episode.last_activity_at = utc_now()
        return self.repository.save(episode)

    def seek(self, episode_id: str, position_seconds: int) -> LiveEpisode:
        episode = self.get(episode_id)
        if position_seconds < 0 or position_seconds > episode.generated_frontier_seconds:
            raise EpisodeRuntimeError("cannot seek beyond the generated frontier")
        episode.playback_position_seconds = position_seconds
        episode.last_activity_at = utc_now()
        return self.repository.save(episode)

    def commit_segment(self, episode_id: str, segment_id: str) -> LiveEpisode:
        episode = self.get(episode_id)
        segment = episode.segment(segment_id)
        if not segment.is_audio_ready:
            raise EpisodeRuntimeError("cannot commit audio that is not ready")
        if segment.state is SegmentState.AUDIO_READY:
            segment.state = SegmentState.COMMITTED
            segment.committed_at = utc_now()
        episode.current_segment_id = segment_id
        episode.last_activity_at = utc_now()
        return self.repository.save(episode)

    def next_playable(self, episode_id: str) -> LiveEpisode:
        episode = self.get(episode_id)
        current_order = episode.segment(episode.current_segment_id).order if episode.current_segment_id else -1
        candidates = [item for item in episode.ordered_segments if item.order > current_order]
        next_segment = next((item for item in candidates if item.is_audio_ready), None)
        # Narration may still be pending. A known music segment can start without a loading wall.
        if next_segment is None:
            next_segment = next((item for item in candidates if item.kind is SegmentKind.MUSIC), None)
            if next_segment is not None:
                self._make_ready(next_segment)
        if next_segment is None:
            raise EpisodeRuntimeError("no future playable segment exists")
        return self.commit_segment(episode_id, next_segment.id)

    def leave(self, episode_id: str) -> LiveEpisode:
        episode = self.get(episode_id)
        episode.is_listener_active = False
        episode.last_activity_at = utc_now()
        return self.repository.save(episode)

    def resume(self, episode_id: str) -> LiveEpisode:
        episode = self.get(episode_id)
        if episode.state is EpisodeState.MATERIALIZED:
            return episode
        episode.is_listener_active = True
        episode.state = EpisodeState.STREAMING
        episode.last_activity_at = utc_now()
        return self.repository.save(episode)

    def materialize_all(self, episode_id: str) -> LiveEpisode:
        episode = self.get(episode_id)
        episode.generation_mode = GenerationMode.FULL
        episode.state = EpisodeState.MATERIALIZING
        for segment in episode.ordered_segments:
            if not segment.is_audio_ready:
                self._make_ready(segment)
        episode.state = EpisodeState.MATERIALIZED
        episode.is_listener_active = True
        episode.last_activity_at = utc_now()
        return self.repository.save(episode)

    def replace_speculative_music(self, episode_id: str, replacement_title: str) -> LiveEpisode:
        """A bounded replan seam: committed content is never changed."""
        episode = self.get(episode_id)
        candidate = next(
            (
                item
                for item in episode.ordered_segments
                if item.kind is SegmentKind.MUSIC and not item.is_committed and item.state is SegmentState.PLANNED
            ),
            None,
        )
        if candidate is None:
            return episode
        candidate.title = replacement_title
        candidate.track_ref = f"mock:replanned:{candidate.order}"
        return self.repository.save(episode)

    @staticmethod
    def _make_ready(segment: Segment) -> None:
        if segment.kind is SegmentKind.NARRATION:
            segment.state = SegmentState.SCRIPT_READY
            segment.narration_text = segment.narration_text or "A short, evidence-aware transition into the next track."
            segment.state = SegmentState.AUDIO_GENERATING
            segment.asset_ref = f"fake-tts://{segment.id}"
        segment.actual_duration_seconds = segment.actual_duration_seconds or segment.planned_duration_seconds
        segment.state = SegmentState.AUDIO_READY

    @staticmethod
    def _future_segments() -> list[Segment]:
        return [
            Segment(
                id="segment-narration-1", chapter_id="chapter-2", order=1, kind=SegmentKind.NARRATION,
                planned_duration_seconds=10, title="Host introduction",
            ),
            Segment(
                id="segment-bridge", chapter_id="chapter-2", order=2, kind=SegmentKind.MUSIC,
                planned_duration_seconds=24, track_ref="mock:bridge", title="Midnight Transfer", artist="Signal Garden",
            ),
            Segment(
                id="segment-narration-2", chapter_id="chapter-3", order=3, kind=SegmentKind.NARRATION,
                planned_duration_seconds=11, title="Host connection",
            ),
            Segment(
                id="segment-resolution", chapter_id="chapter-3", order=4, kind=SegmentKind.MUSIC,
                planned_duration_seconds=26, track_ref="mock:resolution", title="Daybreak in Stereo", artist="Southbound FM",
            ),
        ]
