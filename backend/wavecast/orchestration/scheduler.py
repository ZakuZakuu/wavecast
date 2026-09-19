from typing import Protocol

from wavecast.models.episode import LiveEpisode

from .episode import DEFAULT_BUFFER_AHEAD_SECONDS, EpisodeOrchestrator


class GenerationScheduler(Protocol):
    def ensure_buffer(
        self,
        episode_id: str,
        *,
        target_chapters: int = 2,
        target_ahead_seconds: int = DEFAULT_BUFFER_AHEAD_SECONDS,
    ) -> LiveEpisode: ...


class InlineGenerationScheduler:
    """Mock scheduler seam; Phase 1.5 intentionally has no external worker/queue."""

    def __init__(self, orchestrator: EpisodeOrchestrator) -> None:
        self.orchestrator = orchestrator

    def ensure_buffer(
        self,
        episode_id: str,
        *,
        target_chapters: int = 2,
        target_ahead_seconds: int = DEFAULT_BUFFER_AHEAD_SECONDS,
    ) -> LiveEpisode:
        return self.orchestrator.ensure_buffer(
            episode_id,
            target_chapters=target_chapters,
            target_ahead_seconds=target_ahead_seconds,
        )
