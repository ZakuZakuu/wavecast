from typing import Protocol

from wavecast.models.episode import LiveEpisode

from .episode import EpisodeOrchestrator


class GenerationScheduler(Protocol):
    def ensure_buffer(self, episode_id: str, *, target_chapters: int = 2) -> LiveEpisode: ...


class InlineGenerationScheduler:
    """Mock scheduler seam; Phase 1.5 intentionally has no external worker/queue."""

    def __init__(self, orchestrator: EpisodeOrchestrator) -> None:
        self.orchestrator = orchestrator

    def ensure_buffer(self, episode_id: str, *, target_chapters: int = 2) -> LiveEpisode:
        return self.orchestrator.ensure_buffer(episode_id, target_chapters=target_chapters)
