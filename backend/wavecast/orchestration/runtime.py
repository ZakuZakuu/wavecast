from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from wavecast.intelligence.models import ResolvedTrack
from wavecast.models.episode import (
    GenerationMode,
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    SegmentState,
)
from wavecast.models.progressive import ProgressiveAssemblySession
from wavecast.orchestration.generation import GeneratedChapter, ProgressiveChapterGenerator
from wavecast.providers.usage import scoped_to_episode

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

    @scoped_to_episode
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
        from wavecast.assembly import LiveEpisodeAssemblyRequest, route_limits_for_duration

        max_tracks, max_chapters = route_limits_for_duration(
            episode.program_estimated_duration_seconds, scaled=self.assembly.duration_scaling
        )
        request = LiveEpisodeAssemblyRequest(
            topic=episode.topic,
            anchor_tracks=[opening.title],
            desired_duration_seconds=episode.program_estimated_duration_seconds,
            max_tracks=max_tracks,
            max_chapters=max_chapters,
            presentation_intent=episode.presentation_intent,
            output_language=episode.output_language,
            station=episode.station,
            required_artists=list(episode.required_artists),
        )
        return await self.assembly.prepare_fast_successor(
            request,
            opening_track=opening_track,
        )

    @scoped_to_episode
    async def author_fast_successor_narration(
        self, episode: LiveEpisode
    ) -> GeneratedChapter | None:
        """Write the first A -> B host bridge from durable playback identity only."""

        from wavecast.assembly import (
            EpisodeAssemblyError,
            NarrationPlacementError,
            _assemble_writer_scripts,
            _assert_narration_blocks_materialized,
            _generated_runtime_chapter,
        )
        from wavecast.composer import PreparedMusicAsset
        from wavecast.intelligence.models import (
            ChapterPlan,
            NarrationSlotContext,
            NarrationSlotPlacement,
            NarrativeRole,
            RadioScriptBlockKind,
            TrackProposal,
        )
        from wavecast.presentation import HostMode
        from wavecast.providers.contracts import AudioAsset, AudioAssetType
        from wavecast.providers.errors import ProviderError
        from wavecast.providers.profiles import InferenceProfile

        if episode.presentation_intent.host_mode is HostMode.NONE:
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
        successor = next(
            (
                segment
                for segment in episode.ordered_segments
                if segment.chapter_id == "chapter-2"
                and isinstance(segment, MusicSegment)
                and segment.track_ref
                and segment.artist
                and segment.title
                and segment.audio_source_url
            ),
            None,
        )
        pending = next(
            (
                segment
                for segment in episode.ordered_segments
                if segment.chapter_id == "chapter-2"
                and isinstance(segment, NarrationSegment)
                and segment.state is SegmentState.PLANNED
            ),
            None,
        )
        if opening is None or successor is None or pending is None or not episode.topic:
            return None

        opening_track_ref = opening.track_ref
        opening_artist = opening.artist
        opening_title = opening.title
        successor_track_ref = successor.track_ref
        successor_artist = successor.artist
        successor_title = successor.title
        successor_url = successor.audio_source_url
        assert opening_track_ref and opening_artist and opening_title
        assert successor_track_ref and successor_artist and successor_title and successor_url

        opening_track = ResolvedTrack(
            track_ref=opening_track_ref,
            canonical_artist=opening_artist,
            canonical_title=opening_title,
        )
        successor_track = ResolvedTrack(
            track_ref=successor_track_ref,
            canonical_artist=successor_artist,
            canonical_title=successor_title,
        )
        chapter = ChapterPlan(
            index=1,
            track=TrackProposal(
                artist=successor_track.canonical_artist,
                title=successor_track.canonical_title,
                reasons=["FastStart successor already resolved for playback."],
                confidence=1.0,
            ),
            narrative_role=NarrativeRole.BRIDGE,
            reason="Connect the opening to the already prepared successor.",
            narration_goal=(
                "Give one concise spoken bridge from the track just heard to the "
                "already prepared next track without unsupported factual claims."
            ),
        )
        slot = NarrationSlotContext(
            slot_id="fast-successor:before-track",
            chapter_index=1,
            placement=NarrationSlotPlacement.BEFORE_TRACK,
            allowed_block_kinds=[RadioScriptBlockKind.TRACK_INTRO],
            chapter_track=successor_track,
            just_played_track=opening_track,
            upcoming_track=successor_track,
        )
        target_seconds = (
            24
            if episode.presentation_intent.host_mode is HostMode.FULL
            else 12
        )
        try:
            script = await self.assembly.background_pipeline.writer.write(
                chapter,
                [],
                next_track_metadata=(
                    f"{successor_track.canonical_artist} - "
                    f"{successor_track.canonical_title}"
                ),
                host_mode=episode.presentation_intent.host_mode,
                target_duration_seconds=target_seconds,
                output_language=episode.output_language,
                station=episode.station,
                voice_seed=episode.seed_id,
                topic=episode.topic,
                slot_contexts=[slot],
                inference_profile=InferenceProfile.FAST,
            )
            radio_script, _ = _assemble_writer_scripts(
                [script],
                1,
                chapter_music_indices=[0],
                slot_contexts=[[slot]],
                previous_music_indices=[0],
                require_final_slot=False,
            )
            if not radio_script.blocks:
                return None
            metadata = (
                {
                    "timing_profile": successor.timing_profile.model_dump(
                        mode="json"
                    )
                }
                if successor.timing_profile is not None
                else {}
            )
            prepared = PreparedMusicAsset(
                track=successor_track,
                asset=AudioAsset(
                    asset_id=successor.asset_ref or f"persisted:{successor.track_ref}",
                    asset_type=AudioAssetType.MUSIC,
                    provider="persisted",
                    playback_url=successor_url,
                    duration=successor.duration_seconds,
                    metadata=metadata,
                ),
            )
            playable = self.assembly.composer.compose_prepared(
                [prepared],
                radio_script,
            )
            _assert_narration_blocks_materialized(radio_script, playable)
        except (
            ProviderError,
            NarrationPlacementError,
            EpisodeAssemblyError,
            ValueError,
        ):
            return None

        return _generated_runtime_chapter(
            "chapter-2",
            playable.segments,
            base_order=min(
                segment.order
                for segment in episode.ordered_segments
                if segment.chapter_id == "chapter-2"
            ),
        )

    @scoped_to_episode
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
        from wavecast.assembly import LiveEpisodeAssemblyRequest, route_limits_for_duration

        max_tracks, max_chapters = route_limits_for_duration(
            episode.program_estimated_duration_seconds, scaled=self.assembly.duration_scaling
        )
        request = LiveEpisodeAssemblyRequest(
            topic=episode.topic,
            anchor_tracks=[opening.title],
            desired_duration_seconds=episode.program_estimated_duration_seconds,
            max_tracks=max_tracks,
            max_chapters=max_chapters,
            presentation_intent=episode.presentation_intent,
            output_language=episode.output_language,
            station=episode.station,
            required_artists=list(episode.required_artists),
            variety_seed=episode.seed_id,
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
        # Local import avoids a module-load cycle while keeping the
        # degradable boundary typed: programmer errors must still escape.
        from wavecast.assembly import EpisodeAssemblyError

        try:
            return await self.assembly.prepare_progressive_session(
                request,
                opening_track=opening_track,
                locked_successor=locked_successor,
            )
        except EpisodeAssemblyError as error:
            if error.reason_code == "insufficient_progressive_duration_coverage":
                # An underfilled route is not editorially complete. Let the
                # generation worker retry Research/Curator/resolution instead of
                # converting the playable prefix into a false final/outro.
                raise
            if (
                locked_successor is not None
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

    @scoped_to_episode
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
