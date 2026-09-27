from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from wavecast.intelligence.models import OutputLanguage, ResolvedTrack
from wavecast.models.episode import GenerationMode, LiveEpisode, MusicSegment, NarrationSegment
from wavecast.models.progressive import ProgressiveAssemblySession
from wavecast.orchestration.generation import GeneratedChapter, ProgressiveChapterGenerator

if TYPE_CHECKING:
    from wavecast.assembly import LiveEpisodeAssemblyService, StagedProgressiveChapterGenerator


class ProgressivePlanningDeferred(RuntimeError):
    """Full route planning may retry later because continuity is already safe."""


class StagedProgressiveRuntime(Protocol):
    async def prepare_fast_successor(
        self, episode: LiveEpisode
    ) -> GeneratedChapter | None: ...

    async def prepare_session(self, episode: LiveEpisode) -> ProgressiveAssemblySession: ...

    def create_generator(
        self, session: ProgressiveAssemblySession
    ) -> ProgressiveChapterGenerator: ...

    async def author_narration(
        self, episode: LiveEpisode, chapter_id: str
    ) -> GeneratedChapter | None: ...

    async def materialize_narration(
        self, segment: NarrationSegment
    ) -> NarrationSegment: ...


class StagedProgressiveRuntimeAdapter:
    """Rebuild staged preparation and chapter generation from durable episode state."""

    def __init__(self, assembly: LiveEpisodeAssemblyService) -> None:
        self.assembly = assembly

    async def prepare_fast_successor(
        self, episode: LiveEpisode
    ) -> GeneratedChapter | None:
        if not episode.topic:
            return None
        opening = next(
            (
                segment
                for segment in episode.ordered_segments
                if segment.chapter_id == "chapter-1"
                and isinstance(segment, MusicSegment)
                and segment.track_ref
                and segment.artist
                and segment.title
            ),
            None,
        )
        if opening is None:
            return None
        opening_track_ref = opening.track_ref
        opening_artist = opening.artist
        opening_title = opening.title
        assert opening_track_ref and opening_artist and opening_title
        opening_track = ResolvedTrack(
            track_ref=opening_track_ref,
            canonical_artist=opening_artist,
            canonical_title=opening_title,
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
        return await self.assembly.prepare_fast_successor(
            request,
            opening_track=opening_track,
        )

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
        locked_segment = next(
            (
                segment
                for segment in episode.ordered_segments
                if segment.chapter_id == "chapter-2"
                and isinstance(segment, MusicSegment)
                and segment.track_ref
                and segment.artist
                and segment.title
            ),
            None,
        )
        if locked_segment is None:
            locked_successor = None
        else:
            locked_track_ref = locked_segment.track_ref
            locked_artist = locked_segment.artist
            locked_title = locked_segment.title
            assert locked_track_ref and locked_artist and locked_title
            locked_successor = ResolvedTrack(
                track_ref=locked_track_ref,
                canonical_artist=locked_artist,
                canonical_title=locked_title,
            )
        try:
            return await self.assembly.prepare_progressive_session(
                request,
                opening_track=opening_track,
                locked_successor=locked_successor,
            )
        except Exception as error:
            # The assembly layer exposes a typed EpisodeAssemblyError, but importing
            # it at module load time would create a runtime cycle. Only that known
            # planning failure is degradable, and only while progressive listening
            # already owns a durable successor. FULL generation remains strict.
            from wavecast.assembly import EpisodeAssemblyError

            if (
                isinstance(error, EpisodeAssemblyError)
                and locked_successor is not None
                and episode.generation_mode is GenerationMode.PROGRESSIVE
            ):
                raise ProgressivePlanningDeferred(
                    "full route planning deferred behind ready successor"
                ) from error
            raise

    def create_generator(
        self, session: ProgressiveAssemblySession
    ) -> StagedProgressiveChapterGenerator:
        return self.assembly.create_progressive_chapter_generator(session)

    async def author_narration(
        self, episode: LiveEpisode, chapter_id: str
    ) -> GeneratedChapter | None:
        if episode.progressive_session is None:
            return None
        generator = self.create_generator(episode.progressive_session)
        return await generator.author_narration(episode, chapter_id)

    async def materialize_narration(
        self, segment: NarrationSegment
    ) -> NarrationSegment:
        return await self.assembly.materializer.materialize(segment)
