import asyncio

from wavecast.assembly import StagedProgressiveChapterGenerator
from wavecast.composer import EpisodeComposer
from wavecast.intelligence.models import (
    ChapterPlan,
    FastStartPlan,
    NarrationScript,
    NarrationSlotContext,
    NarrationSlotPlacement,
    NarrativeRole,
    OutputLanguage,
    ProgramSkeleton,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResearchBundle,
    ResolvedTrack,
)
from wavecast.materialization import NarrationMaterializer
from wavecast.models.episode import (
    EpisodeState,
    LiveEpisode,
    MusicSegment,
    SegmentState,
)
from wavecast.orchestration.staged import (
    ProgressiveAssemblyChapter,
    ProgressiveAssemblySession,
)
from wavecast.providers.fakes import MockMusicProvider, MockTTSProvider
from wavecast.storage.assets import LocalObjectStorageProvider
from wavecast.timing import build_program_timing_plan


def _session(track: ResolvedTrack) -> ProgressiveAssemblySession:
    chapter = ChapterPlan(
        index=0,
        track=None,
        narrative_role=NarrativeRole.BRIDGE,
        reason="connect the opening to the next track",
        narration_goal="explain the audible connection",
    )
    slots = [
        NarrationSlotContext(
            slot_id="chapter-0:before-track",
            chapter_index=0,
            placement=NarrationSlotPlacement.BEFORE_TRACK,
            allowed_block_kinds=[RadioScriptBlockKind.TRACK_INTRO],
            chapter_track=track,
            just_played_track=ResolvedTrack(
                track_ref="mock:opening",
                canonical_artist="Opening Artist",
                canonical_title="Opening Track",
            ),
            upcoming_track=track,
        ),
        NarrationSlotContext(
            slot_id="chapter-0:after-final",
            chapter_index=0,
            placement=NarrationSlotPlacement.AFTER_FINAL_TRACK,
            allowed_block_kinds=[RadioScriptBlockKind.OUTRO],
            chapter_track=track,
            just_played_track=track,
            is_final=True,
        ),
    ]
    return ProgressiveAssemblySession(
        topic="fixture",
        desired_duration_seconds=900,
        max_tracks=2,
        max_chapters=2,
        output_language=OutputLanguage.EN_US,
        opening_track_ref="mock:opening",
        fast_plan=FastStartPlan(
            anchor_understanding=["opening"],
            immediate_taste_hypotheses=[],
            next_candidates=[],
            first_narration=NarrationScript(
                text="Start here.",
                intended_duration_seconds=1,
            ),
        ),
        research=ResearchBundle(
            anchors=[],
            taste_hypotheses=[],
            evidence=[],
            candidates=[],
        ),
        skeleton=ProgramSkeleton(
            thesis="fixture",
            chapters=[chapter],
            estimated_duration_seconds=900,
        ),
        chapters=[
            ProgressiveAssemblyChapter(
                chapter_id="chapter-2",
                chapter=chapter,
                resolved_track=track,
                slot_contexts=slots,
                target_narration_seconds=2,
            )
        ],
        timing_plan=build_program_timing_plan(
            desired_total_seconds=900,
            target_narration_ratio=0.15,
            resolved_music_seconds=180,
            chapter_slot_counts=[2],
        ),
    )


def _episode() -> LiveEpisode:
    return LiveEpisode(
        seed_id="seed",
        state=EpisodeState.STREAMING,
        program_estimated_duration_seconds=900,
        segments=[
            MusicSegment(
                id="opening",
                chapter_id="chapter-1",
                order=0,
                state=SegmentState.COMMITTED,
                planned_duration_seconds=120,
                actual_duration_seconds=120,
                track_ref="mock:opening",
                audio_source_url="/api/audio/mock/opening",
                title="Opening Track",
                artist="Opening Artist",
            )
        ],
    )


class _Writer:
    async def write(self, *args: object, **kwargs: object) -> RadioScript:
        return RadioScript(
            blocks=[
                RadioScriptBlock(
                    kind=RadioScriptBlockKind.TRACK_INTRO,
                    text="Listen for the shared pocket.",
                    duration_seconds=1,
                ),
                RadioScriptBlock(
                    kind=RadioScriptBlockKind.OUTRO,
                    text="That connection closes this short route.",
                    duration_seconds=1,
                ),
            ],
            intended_duration_seconds=2,
        )


def test_staged_generator_materializes_one_complete_runtime_chunk(tmp_path) -> None:
    track = ResolvedTrack(
        track_ref="mock:bridge",
        canonical_artist="Bridge Artist",
        canonical_title="Bridge Track",
    )
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    generator = StagedProgressiveChapterGenerator(
        session=_session(track),
        writer=_Writer(),  # type: ignore[arg-type]
        composer=EpisodeComposer(MockMusicProvider()),
        materializer=NarrationMaterializer(MockTTSProvider(storage), storage),
    )

    generated = asyncio.run(generator.generate_next(_episode()))

    assert generated is not None
    assert generated.chapter_id == "chapter-2"
    assert len(generated.segments) == 3
    assert all(segment.chapter_id == "chapter-2" for segment in generated.segments)
    assert all(segment.is_audio_ready for segment in generated.segments)
    assert any(isinstance(segment, MusicSegment) for segment in generated.segments)
