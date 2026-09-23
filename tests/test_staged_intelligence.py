from wavecast.intelligence.models import (
    ChapterPlan,
    FastStartPlan,
    NarrationScript,
    NarrativeRole,
    OutputLanguage,
    ProgramSkeleton,
    ResearchBundle,
)
from wavecast.models.episode import EpisodeState, LiveEpisode, MusicSegment, SegmentState
from wavecast.orchestration.staged import (
    ProgressiveAssemblyChapter,
    ProgressiveAssemblySession,
)
from wavecast.timing import build_program_timing_plan


def _session() -> ProgressiveAssemblySession:
    chapters = [
        ProgressiveAssemblyChapter(
            chapter_id="chapter-2",
            chapter=ChapterPlan(
                index=0,
                narrative_role=NarrativeRole.ANCHOR,
                reason="Open the route.",
                narration_goal="Introduce the first connection.",
            ),
            target_narration_seconds=1,
        ),
        ProgressiveAssemblyChapter(
            chapter_id="chapter-3",
            chapter=ChapterPlan(
                index=1,
                narrative_role=NarrativeRole.BRIDGE,
                reason="Extend the route.",
                narration_goal="Explain the next connection.",
            ),
            target_narration_seconds=1,
        ),
    ]
    return ProgressiveAssemblySession(
        topic="A guided route",
        desired_duration_seconds=900,
        max_tracks=4,
        max_chapters=8,
        output_language=OutputLanguage.EN_US,
        fast_plan=FastStartPlan(
            anchor_understanding=["An anchor"],
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
            thesis="A route",
            chapters=[
                chapters[0].chapter,
                chapters[1].chapter,
            ],
            estimated_duration_seconds=900,
        ),
        chapters=chapters,
        timing_plan=build_program_timing_plan(
            desired_total_seconds=900,
            target_narration_ratio=0.15,
            resolved_music_seconds=600,
            chapter_slot_counts=[1, 1],
        ),
    )


def _episode(*chapter_ids: str) -> LiveEpisode:
    segments = [
        MusicSegment(
            id=f"music-{index}",
            chapter_id=chapter_id,
            order=index,
            state=SegmentState.AUDIO_READY,
            planned_duration_seconds=120,
            actual_duration_seconds=120,
            track_ref=f"mock:track-{index}",
            title=f"Track {index}",
            artist="Artist",
        )
        for index, chapter_id in enumerate(chapter_ids)
    ]
    return LiveEpisode(
        seed_id="seed",
        state=EpisodeState.STREAMING,
        program_estimated_duration_seconds=900,
        segments=segments,
    )


def test_session_round_trips_without_provider_or_cursor_state() -> None:
    session = _session()

    restored = ProgressiveAssemblySession.model_validate_json(session.model_dump_json())

    assert restored.model_dump() == session.model_dump()
    assert "next_chapter_index" not in restored.model_dump()
    assert "_provider" not in restored.model_dump()
    assert restored.schema_version == 1


def test_next_chapter_is_derived_from_persisted_episode_timeline() -> None:
    session = _session()

    next_chapter = session.next_chapter(_episode("chapter-1"))
    assert next_chapter is not None
    assert next_chapter.chapter_id == "chapter-2"

    next_chapter = session.next_chapter(_episode("chapter-1", "chapter-2"))
    assert next_chapter is not None
    assert next_chapter.chapter_id == "chapter-3"
    assert session.next_chapter(_episode("chapter-1", "chapter-2", "chapter-3")) is None
