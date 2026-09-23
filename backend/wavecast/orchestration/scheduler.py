from __future__ import annotations

import asyncio
from typing import Protocol

from wavecast.models.episode import LiveEpisode

from .episode import DEFAULT_BUFFER_AHEAD_SECONDS, EpisodeOrchestrator


class GenerationScheduler(Protocol):
    async def ensure_buffer(
        self,
        episode_id: str,
        *,
        target_chapters: int = 2,
        target_ahead_seconds: int = DEFAULT_BUFFER_AHEAD_SECONDS,
    ) -> LiveEpisode: ...

    async def materialize_all(self, episode_id: str) -> LiveEpisode: ...


class InlineGenerationScheduler:
    """Bounded in-process scheduler; no external worker or queue is required yet."""

    def __init__(self, orchestrator: EpisodeOrchestrator) -> None:
        self.orchestrator = orchestrator
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, episode_id: str) -> asyncio.Lock:
        return self._locks.setdefault(episode_id, asyncio.Lock())

    async def ensure_buffer(
        self,
        episode_id: str,
        *,
        target_chapters: int = 2,
        target_ahead_seconds: int = DEFAULT_BUFFER_AHEAD_SECONDS,
    ) -> LiveEpisode:
        async with self._lock_for(episode_id):
            return await self.orchestrator.ensure_buffer_async(
                episode_id,
                target_chapters=target_chapters,
                target_ahead_seconds=target_ahead_seconds,
            )

    async def materialize_all(self, episode_id: str) -> LiveEpisode:
        async with self._lock_for(episode_id):
            return await self.orchestrator.materialize_all_async(episode_id)
