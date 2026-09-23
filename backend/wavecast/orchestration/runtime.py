from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from wavecast.intelligence.models import OutputLanguage, ResolvedTrack
from wavecast.models.episode import LiveEpisode
from wavecast.models.progressive import ProgressiveAssemblySession
from wavecast.orchestration.generation import ProgressiveChapterGenerator

if TYPE_CHECKING:
    from wavecast.assembly import LiveEpisodeAssemblyService, StagedProgressiveChapterGenerator


class StagedProgressiveRuntime(Protocol):
    async def prepare_session(self, episode: LiveEpisode) -> ProgressiveAssemblySession: ...

    def create_generator(
        self, session: ProgressiveAssemblySession
    ) -> ProgressiveChapterGenerator: ...


class StagedProgressiveRuntimeAdapter:
    """Rebuild staged preparation and chapter generation from durable episode state."""

    def __init__(self, assembly: LiveEpisodeAssemblyService) -> None:
        self.assembly = assembly

    async def prepare_session(self, episode: LiveEpisode) -> ProgressiveAssemblySession:
        if not episode.topic:
            raise ValueError("progressive session requires episode topic")
        opening = next(
            (
                segment
                for segment in episode.ordered_segments
                if segment.chapter_id == "chapter-1"
                and segment.track_ref is not None
                and segment.artist
                and segment.title
            ),
            None,
        )
        if opening is None:
            raise ValueError("progressive session requires a persisted opening track")
        track_ref = opening.track_ref
        artist = opening.artist
        title = opening.title
        assert track_ref is not None and artist is not None and title is not None
        opening_track = ResolvedTrack(
            track_ref=track_ref,
            canonical_artist=artist,
            canonical_title=title,
        )
        from wavecast.assembly import LiveEpisodeAssemblyRequest

        request = LiveEpisodeAssemblyRequest(
            topic=episode.topic,
            anchor_tracks=[opening.title],
            desired_duration_seconds=episode.program_estimated_duration_seconds,
            max_tracks=5,
            max_chapters=8,
            output_language=OutputLanguage.AUTO,
        )
        return await self.assembly.prepare_progressive_session(
            request,
            opening_track=opening_track,
        )

    def create_generator(
        self, session: ProgressiveAssemblySession
    ) -> StagedProgressiveChapterGenerator:
        return self.assembly.create_progressive_chapter_generator(session)
