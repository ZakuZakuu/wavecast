from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from wavecast.intelligence.models import ChapterPlan, NarrationSlotContext
from wavecast.models.episode import (
    EpisodeState,
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    SegmentState,
)
from wavecast.models.progressive import ProgressiveAssemblyChapter, ProgressiveAssemblySession
from wavecast.orchestration.episode import InMemoryEpisodeRepository
from wavecast.orchestration.generation import GeneratedChapter
from wavecast.orchestration.narration_enrichment import _finish_authoring, author_pending_narration


class _Host:
    progressive_runtime = None

    def __init__(self, repository: InMemoryEpisodeRepository) -> None:
        self.repository = repository
        self.now = lambda: datetime(2026, 9, 27, tzinfo=UTC)


def _episode(*, music_state: SegmentState = SegmentState.AUDIO_READY) -> LiveEpisode:
    session = ProgressiveAssemblySession.model_construct(
        narration_authored_chapter_ids=[],
    )
    return LiveEpisode(
        seed_id="seed",
        state=EpisodeState.STREAMING,
        program_estimated_duration_seconds=900,
        progressive_session=session,
        current_segment_id=(
            "chapter-2:music:0"
            if music_state is SegmentState.COMMITTED
            else "opening"
        ),
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
                title="Opening",
                artist="Opening Artist",
            ),
            MusicSegment(
                id="chapter-2:music:0",
                chapter_id="chapter-2",
                order=1,
                state=music_state,
                planned_duration_seconds=180,
                actual_duration_seconds=180,
                track_ref="mock:bridge",
                audio_source_url="/api/audio/mock/bridge",
                title="Bridge",
                artist="Bridge Artist",
            ),
            MusicSegment(
                id="chapter-3:music:0",
                chapter_id="chapter-3",
                order=2,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=180,
                actual_duration_seconds=180,
                track_ref="mock:next",
                audio_source_url="/api/audio/mock/next",
                title="Next",
                artist="Next Artist",
            ),
        ],
    )


def _authored_chapter() -> GeneratedChapter:
    return GeneratedChapter(
        chapter_id="chapter-2",
        segments=[
            NarrationSegment(
                id="chapter-2:narration:0",
                chapter_id="chapter-2",
                order=1,
                state=SegmentState.SCRIPT_READY,
                planned_duration_seconds=8,
                title="Bridge intro",
                narration_text="A short connection.",
            ),
            MusicSegment(
                id="chapter-2:music:0",
                chapter_id="chapter-2",
                order=2,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=180,
                actual_duration_seconds=180,
                track_ref="mock:bridge",
                audio_source_url="/api/audio/mock/bridge",
                title="Bridge",
                artist="Bridge Artist",
            ),
        ],
    )


def test_writer_enrichment_inserts_script_before_speculative_music() -> None:
    repository = InMemoryEpisodeRepository()
    episode = _episode()
    repository.save(episode)

    updated = _finish_authoring(
        _Host(repository),
        episode.id,
        "chapter-2",
        _authored_chapter(),
    )

    chapter = [
        segment
        for segment in updated.ordered_segments
        if segment.chapter_id == "chapter-2"
    ]
    assert [segment.id for segment in chapter] == [
        "chapter-2:narration:0",
        "chapter-2:music:0",
    ]
    assert chapter[0].state is SegmentState.SCRIPT_READY
    assert chapter[1].audio_source_url == "/api/audio/mock/bridge"
    assert updated.segment("chapter-3:music:0").order == 3
    assert updated.progressive_session is not None
    assert updated.progressive_session.narration_authored_chapter_ids == ["chapter-2"]


def test_late_writer_enrichment_never_rewrites_committed_music() -> None:
    repository = InMemoryEpisodeRepository()
    episode = _episode(music_state=SegmentState.COMMITTED)
    repository.save(episode)

    updated = _finish_authoring(
        _Host(repository),
        episode.id,
        "chapter-2",
        _authored_chapter(),
    )

    chapter = [
        segment
        for segment in updated.ordered_segments
        if segment.chapter_id == "chapter-2"
    ]
    assert [segment.id for segment in chapter] == ["chapter-2:music:0"]
    assert chapter[0].state is SegmentState.COMMITTED
    assert updated.segment("chapter-3:music:0").order == 2
    assert updated.progressive_session is not None
    assert updated.progressive_session.narration_authored_chapter_ids == ["chapter-2"]


def _trackless_episode(
    *,
    next_state: SegmentState = SegmentState.AUDIO_READY,
) -> LiveEpisode:
    session = ProgressiveAssemblySession.model_construct(
        narration_authored_chapter_ids=[],
    )
    return LiveEpisode(
        seed_id="seed-trackless",
        state=EpisodeState.STREAMING,
        program_estimated_duration_seconds=900,
        progressive_session=session,
        current_segment_id=(
            "chapter-3:music:0"
            if next_state is SegmentState.COMMITTED
            else "opening-trackless"
        ),
        segments=[
            MusicSegment(
                id="opening-trackless",
                chapter_id="chapter-1",
                order=0,
                state=SegmentState.COMMITTED,
                planned_duration_seconds=120,
                actual_duration_seconds=120,
                track_ref="mock:opening",
                audio_source_url="/api/audio/mock/opening",
                title="Opening",
                artist="Opening Artist",
            ),
            NarrationSegment(
                id="chapter-2:narration:0",
                chapter_id="chapter-2",
                order=1,
                state=SegmentState.SKIPPED,
                planned_duration_seconds=8,
                title="Optional narration skipped",
            ),
            MusicSegment(
                id="chapter-3:music:0",
                chapter_id="chapter-3",
                order=2,
                state=next_state,
                planned_duration_seconds=180,
                actual_duration_seconds=180,
                track_ref="mock:next",
                audio_source_url="/api/audio/mock/next",
                title="Next",
                artist="Next Artist",
            ),
        ],
    )


def _authored_trackless_chapter() -> GeneratedChapter:
    return GeneratedChapter(
        chapter_id="chapter-2",
        segments=[
            NarrationSegment(
                id="chapter-2:narration:0",
                chapter_id="chapter-2",
                order=1,
                state=SegmentState.SCRIPT_READY,
                planned_duration_seconds=8,
                title="Story beat",
                narration_text="A short scene-setting beat.",
            )
        ],
    )


def test_writer_enrichment_restores_trackless_narration_while_still_speculative() -> None:
    repository = InMemoryEpisodeRepository()
    episode = _trackless_episode()
    repository.save(episode)

    updated = _finish_authoring(
        _Host(repository),
        episode.id,
        "chapter-2",
        _authored_trackless_chapter(),
    )

    narration = updated.segment("chapter-2:narration:0")
    assert narration.state is SegmentState.SCRIPT_READY
    assert narration.narration_text == "A short scene-setting beat."
    assert updated.segment("chapter-3:music:0").order == 2
    assert updated.progressive_session is not None
    assert updated.progressive_session.narration_authored_chapter_ids == ["chapter-2"]


def test_late_trackless_writer_never_inserts_before_committed_future_music() -> None:
    repository = InMemoryEpisodeRepository()
    episode = _trackless_episode(next_state=SegmentState.COMMITTED)
    repository.save(episode)

    updated = _finish_authoring(
        _Host(repository),
        episode.id,
        "chapter-2",
        _authored_trackless_chapter(),
    )

    narration = updated.segment("chapter-2:narration:0")
    assert narration.state is SegmentState.SKIPPED
    assert narration.narration_text is None
    assert updated.segment("chapter-3:music:0").order == 2
    assert updated.progressive_session is not None
    assert updated.progressive_session.narration_authored_chapter_ids == ["chapter-2"]


class _ExplodingRuntime:
    async def author_narration(
        self,
        episode: LiveEpisode,
        chapter_id: str,
    ) -> GeneratedChapter | None:
        del episode, chapter_id
        raise RuntimeError("synthetic writer crash")


class _ExplodingHost(_Host):
    def __init__(self, repository: InMemoryEpisodeRepository) -> None:
        super().__init__(repository)
        self.progressive_runtime = _ExplodingRuntime()


def test_unexpected_writer_failure_skips_placeholder_and_marks_chapter_authored() -> None:
    repository = InMemoryEpisodeRepository()
    episode = _episode()
    episode.segments.insert(
        1,
        NarrationSegment(
            id="chapter-2:narration:pending",
            chapter_id="chapter-2",
            order=1,
            state=SegmentState.PLANNED,
            planned_duration_seconds=8,
            title="Pending host bridge",
        ),
    )
    episode.segment("chapter-2:music:0").order = 2
    episode.segment("chapter-3:music:0").order = 3
    episode.progressive_session = ProgressiveAssemblySession.model_construct(
        narration_authored_chapter_ids=[],
        chapters=[
            ProgressiveAssemblyChapter.model_construct(
                chapter_id="chapter-2",
                chapter=ChapterPlan.model_construct(track=None),
                resolved_track=None,
                slot_contexts=[NarrationSlotContext.model_construct()],
                target_narration_seconds=8,
            )
        ],
    )
    repository.save(episode)

    updated = asyncio.run(
        author_pending_narration(
            _ExplodingHost(repository),
            episode.id,
            max_chapters=1,
        )
    )

    placeholder = updated.segment("chapter-2:narration:pending")
    assert placeholder.state is SegmentState.SKIPPED
    assert updated.segment("chapter-2:music:0").is_audio_ready
    assert updated.progressive_session is not None
    assert updated.progressive_session.narration_authored_chapter_ids == ["chapter-2"]


class _DegradingRuntime:
    async def author_narration(
        self,
        episode: LiveEpisode,
        chapter_id: str,
    ) -> GeneratedChapter | None:
        del episode, chapter_id
        return None


class _DegradingHost(_Host):
    def __init__(self, repository: InMemoryEpisodeRepository) -> None:
        super().__init__(repository)
        self.progressive_runtime = _DegradingRuntime()


def test_writer_degradation_marks_chapter_authored_without_crashing() -> None:
    repository = InMemoryEpisodeRepository()
    episode = _episode()
    episode.progressive_session = ProgressiveAssemblySession.model_construct(
        narration_authored_chapter_ids=[],
        chapters=[
            ProgressiveAssemblyChapter.model_construct(
                chapter_id="chapter-2",
                chapter=ChapterPlan.model_construct(track=None),
                resolved_track=None,
                slot_contexts=[NarrationSlotContext.model_construct()],
                target_narration_seconds=8,
            )
        ],
    )
    repository.save(episode)

    updated = asyncio.run(
        author_pending_narration(
            _DegradingHost(repository),
            episode.id,
            max_chapters=1,
        )
    )

    assert updated.progressive_session is not None
    assert updated.progressive_session.narration_authored_chapter_ids == ["chapter-2"]
    chapter = [
        segment
        for segment in updated.ordered_segments
        if segment.chapter_id == "chapter-2"
    ]
    assert [segment.id for segment in chapter] == ["chapter-2:music:0"]
    assert chapter[0].state is SegmentState.AUDIO_READY
