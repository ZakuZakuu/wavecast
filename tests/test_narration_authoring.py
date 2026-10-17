from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
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


def _pending_episode() -> tuple[InMemoryEpisodeRepository, LiveEpisode]:
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
    return repository, episode


class _SlowCountingRuntime:
    def __init__(self) -> None:
        self.calls = 0

    async def author_narration(self, episode: LiveEpisode, chapter_id: str) -> GeneratedChapter | None:
        del episode, chapter_id
        self.calls += 1
        await asyncio.sleep(0.05)
        return None


def test_two_authoring_runs_for_the_same_chapter_write_it_once() -> None:
    """The generation job and the detached enrichment both author the next chapter (seen live)."""

    repository, episode = _pending_episode()
    runtime = _SlowCountingRuntime()
    host = _Host(repository)
    host.progressive_runtime = runtime  # type: ignore[assignment]

    async def both() -> None:
        await asyncio.gather(
            author_pending_narration(host, episode.id, max_chapters=1),
            author_pending_narration(host, episode.id, max_chapters=1),
        )

    asyncio.run(both())

    assert runtime.calls == 1


def test_a_failed_authoring_run_releases_the_chapter_for_the_next_one() -> None:
    from wavecast.orchestration import narration_enrichment

    repository, episode = _pending_episode()
    asyncio.run(author_pending_narration(_ExplodingHost(repository), episode.id, max_chapters=1))

    assert narration_enrichment._AUTHORING_IN_FLIGHT == {}


def test_a_second_path_cannot_start_a_chapter_while_the_first_ones_result_is_still_being_saved(
    monkeypatch,
) -> None:
    """Seen live: the guard was released as soon as the Writer returned, before the result was stored."""

    import time

    from wavecast.orchestration import narration_enrichment

    repository, episode = _pending_episode()
    runtime = _SlowCountingRuntime()
    host = _Host(repository)
    host.progressive_runtime = runtime  # type: ignore[assignment]
    original = narration_enrichment._finish_authoring

    def slow_save(*args, **kwargs):  # type: ignore[no-untyped-def]
        time.sleep(0.2)  # the Writer is done; the result is not stored yet
        return original(*args, **kwargs)

    monkeypatch.setattr(narration_enrichment, "_finish_authoring", slow_save)

    async def both() -> None:
        first = asyncio.create_task(author_pending_narration(host, episode.id, max_chapters=1))
        await asyncio.sleep(0.1)  # past the Writer call (0.05 s), inside the save
        await author_pending_narration(host, episode.id, max_chapters=1)
        await first

    asyncio.run(both())

    assert runtime.calls == 1
    assert narration_enrichment._AUTHORING_IN_FLIGHT == {}


def test_a_cancelled_authoring_run_releases_the_chapter() -> None:
    from wavecast.orchestration import narration_enrichment

    class Hangs:
        async def author_narration(self, episode: LiveEpisode, chapter_id: str) -> GeneratedChapter | None:
            del episode, chapter_id
            await asyncio.sleep(3600)
            return None

    repository, episode = _pending_episode()
    host = _Host(repository)
    host.progressive_runtime = Hangs()  # type: ignore[assignment]

    async def run() -> None:
        task = asyncio.create_task(author_pending_narration(host, episode.id, max_chapters=1))
        await asyncio.sleep(0.05)
        assert narration_enrichment._AUTHORING_IN_FLIGHT  # held while it works
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert narration_enrichment._AUTHORING_IN_FLIGHT == {}


@pytest.mark.parametrize("fast_opening", [False, True])
def test_full_generation_joins_the_writer_and_voices_its_result_once(fast_opening) -> None:
    """Real FULL lifecycle must not close seams while detached authoring is pending."""
    from wavecast.orchestration.episode import EpisodeOrchestrator

    class Runtime:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0
            self.tts_calls = 0
            self.generation_calls = 0

        def create_generator(self, session):
            return self

        async def generate_next(self, episode):
            self.generation_calls += 1
            return None

        async def author_narration(self, episode, chapter_id):
            self.calls += 1
            self.entered.set()
            await self.release.wait()
            return _authored_chapter()

        async def author_fast_successor_narration(self, episode):
            return await self.author_narration(episode, "chapter-2")

        async def materialize_narration(self, segment):
            self.tts_calls += 1
            return segment.model_copy(
                update={
                    "state": SegmentState.AUDIO_READY,
                    "actual_duration_seconds": 8,
                    "audio_source_url": "/api/audio/mock/voice",
                    "asset_ref": "voice",
                }
            )

    async def run():
        repository, episode = _pending_episode()
        runtime = Runtime()
        orchestrator = EpisodeOrchestrator(repository, progressive_runtime=runtime)
        detached = asyncio.create_task(
            orchestrator.author_fast_successor_narration_async(episode.id)
            if fast_opening
            else orchestrator.author_pending_narration_async(episode.id)
        )
        await runtime.entered.wait()
        full = asyncio.create_task(orchestrator.materialize_all_async(episode.id))
        await asyncio.sleep(0.05)
        assert not full.done()
        assert (
            repository.get(episode.id).segment("chapter-2:narration:pending").state
            is SegmentState.PLANNED
        )
        runtime.release.set()
        await detached
        completed = await full
        assert completed.state is EpisodeState.MATERIALIZED
        assert completed.segment("chapter-2:narration:0").state is SegmentState.AUDIO_READY
        assert (runtime.calls, runtime.tts_calls) == (1, 1)

    asyncio.run(run())


def test_full_generation_joins_inflight_tts_without_requesting_it_twice() -> None:
    from wavecast.models.episode import GenerationMode
    from wavecast.orchestration.episode import _TTS_IN_FLIGHT, EpisodeOrchestrator

    class Runtime:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def materialize_narration(self, segment):
            self.calls += 1
            self.entered.set()
            await self.release.wait()
            return segment.model_copy(
                update={
                    "state": SegmentState.AUDIO_READY,
                    "actual_duration_seconds": 8,
                    "audio_source_url": "/api/audio/mock/voice",
                    "asset_ref": "voice",
                }
            )

    async def run():
        repository, episode = _pending_episode()
        episode.generation_mode = GenerationMode.FULL
        episode = _finish_authoring(_Host(repository), episode.id, "chapter-2", _authored_chapter())
        runtime = Runtime()
        orchestrator = EpisodeOrchestrator(repository, progressive_runtime=runtime)
        first = asyncio.create_task(orchestrator.materialize_pending_narration_async(episode.id))
        await runtime.entered.wait()
        second = asyncio.create_task(orchestrator.materialize_pending_narration_async(episode.id))
        await asyncio.sleep(0.05)
        assert not second.done()
        runtime.release.set()
        await asyncio.gather(first, second)
        assert runtime.calls == 1
        assert repository.get(episode.id).segment("chapter-2:narration:0").is_audio_ready
        assert not _TTS_IN_FLIGHT

    asyncio.run(run())


def test_cancellation_during_save_keeps_the_authoring_claim_until_the_thread_finishes(monkeypatch):
    import threading

    from wavecast.orchestration import narration_enrichment

    repository, episode = _pending_episode()
    entered, release = threading.Event(), threading.Event()
    original = narration_enrichment._finish_authoring

    def blocked_save(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(narration_enrichment, "_finish_authoring", blocked_save)
    host = _Host(repository)
    host.progressive_runtime = _SlowCountingRuntime()

    async def run():
        first = asyncio.create_task(author_pending_narration(host, episode.id))
        await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        await asyncio.sleep(0.01)
        assert narration_enrichment._AUTHORING_IN_FLIGHT
        await author_pending_narration(host, episode.id)
        assert host.progressive_runtime.calls == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not narration_enrichment._AUTHORING_IN_FLIGHT

    asyncio.run(run())
