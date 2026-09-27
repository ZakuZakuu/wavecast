from __future__ import annotations

import asyncio

import pytest
from wavecast.assembly import create_episode_assembly_service
from wavecast.intelligence.models import ResolvedTrack
from wavecast.models.episode import (
    CoverParams,
    EpisodeSeed,
    EpisodeState,
    MusicSegment,
    SegmentState,
)
from wavecast.orchestration.episode import (
    EpisodeOrchestrator,
    EpisodeRuntimeError,
    InMemoryEpisodeRepository,
)
from wavecast.orchestration.generation import GeneratedChapter
from wavecast.orchestration.runtime import (
    ProgressivePlanningDeferred,
    StagedProgressiveRuntimeAdapter,
)
from wavecast.providers.config import ProviderSettings

from tests.test_staged_intelligence import _session


def _seed() -> EpisodeSeed:
    return EpisodeSeed(
        id="staged-runtime-seed",
        title="Staged runtime",
        topic="A deterministic staged route",
        short_description="test",
        estimated_duration_seconds=900,
        opening_track_ref="mock:opening",
        opening_track_title="Opening Track",
        opening_track_artist="Opening Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
    )


class _CountingRuntime:
    def __init__(self, delegate: StagedProgressiveRuntimeAdapter) -> None:
        self.delegate = delegate
        self.prepare_calls = 0

    async def prepare_session(self, episode):
        self.prepare_calls += 1
        return await self.delegate.prepare_session(episode)

    def create_generator(self, session):
        return self.delegate.create_generator(session)


def test_staged_session_is_persisted_and_reconstructed_without_reprepare() -> None:
    assembly = create_episode_assembly_service(
        ProviderSettings(mode="mock"),
    )
    delegate = StagedProgressiveRuntimeAdapter(assembly)
    runtime_adapter = _CountingRuntime(delegate)
    repository = InMemoryEpisodeRepository()
    first = EpisodeOrchestrator(repository, progressive_runtime=runtime_adapter)
    episode = first.start(_seed())

    first_buffer = asyncio.run(
        first.ensure_buffer_async(
            episode.id,
            target_chapters=1,
            target_ahead_seconds=300,
        )
    )

    assert first_buffer.progressive_session is not None
    assert runtime_adapter.prepare_calls == 1
    assert "progressive_session" not in first_buffer.model_dump(mode="json")
    assert {segment.chapter_id for segment in first_buffer.segments} >= {
        "chapter-1",
        "chapter-2",
    }

    reconstructed_adapter = _CountingRuntime(
        StagedProgressiveRuntimeAdapter(assembly)
    )
    second = EpisodeOrchestrator(repository, progressive_runtime=reconstructed_adapter)
    second_buffer = asyncio.run(
        second.ensure_buffer_async(
            episode.id,
            target_chapters=2,
            target_ahead_seconds=300,
        )
    )

    assert reconstructed_adapter.prepare_calls == 0
    assert second_buffer.progressive_session is not None
    assert "chapter-3" in {segment.chapter_id for segment in second_buffer.segments}


class _FakeRuntime:
    def __init__(self, *, gated: bool = False, fail_first_generation: bool = False) -> None:
        self.prepare_calls = 0
        self.create_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.gated = gated
        self.fail_first_generation = fail_first_generation

    async def prepare_session(self, episode):
        self.prepare_calls += 1
        if self.gated:
            self.started.set()
            await self.release.wait()
        return _session()

    def create_generator(self, session):
        self.create_calls += 1
        should_fail = self.fail_first_generation and self.create_calls == 1
        return _FakeGenerator(session, should_fail=should_fail)


class _FakeGenerator:
    def __init__(self, session, *, should_fail: bool) -> None:
        self.session = session
        self.should_fail = should_fail

    async def generate_next(self, episode):
        if self.should_fail:
            raise RuntimeError("synthetic writer failure")
        chapter = self.session.next_chapter(episode)
        if chapter is None:
            return None
        return GeneratedChapter(
            chapter_id=chapter.chapter_id,
            segments=[
                MusicSegment(
                    id=f"{chapter.chapter_id}:music",
                    chapter_id=chapter.chapter_id,
                    order=0,
                    state=SegmentState.AUDIO_READY,
                    planned_duration_seconds=1,
                    actual_duration_seconds=1,
                    track_ref=f"mock:{chapter.chapter_id}",
                    title=chapter.chapter_id,
                    artist="Fixture Artist",
                )
            ],
        )



class _BootstrapRuntime(_FakeRuntime):
    def __init__(self) -> None:
        super().__init__(gated=True)
        self.fast_calls = 0
        self.fast_track = ResolvedTrack(
            track_ref="mock:fast-successor",
            canonical_artist="Fast Artist",
            canonical_title="Fast Successor",
        )

    async def prepare_fast_successor(self, episode):
        del episode
        self.fast_calls += 1
        return GeneratedChapter(
            chapter_id="chapter-2",
            segments=[
                MusicSegment(
                    id="chapter-2:music:0",
                    chapter_id="chapter-2",
                    order=1,
                    state=SegmentState.AUDIO_READY,
                    planned_duration_seconds=180,
                    actual_duration_seconds=180,
                    track_ref=self.fast_track.track_ref,
                    audio_source_url="/api/audio/mock/fast-successor",
                    title=self.fast_track.canonical_title,
                    artist=self.fast_track.canonical_artist,
                )
            ],
        )

    async def prepare_session(self, episode):
        self.prepare_calls += 1
        self.started.set()
        await self.release.wait()
        base = _session()
        return base.model_copy(
            update={
                "opening_track_ref": "mock:opening",
                "chapters": [
                    base.chapters[0].model_copy(
                        update={"resolved_track": self.fast_track}
                    ),
                    base.chapters[1],
                ],
            }
        )


def test_fast_successor_is_durable_before_full_session_finishes() -> None:
    staged = _BootstrapRuntime()
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(repository, progressive_runtime=staged)
    episode = runtime.start(_seed())

    async def run() -> None:
        task = asyncio.create_task(
            runtime.ensure_buffer_async(
                episode.id,
                target_chapters=1,
                target_ahead_seconds=300,
            )
        )
        await asyncio.wait_for(staged.started.wait(), timeout=1)

        during_planning = repository.get(episode.id)
        successor = during_planning.segment("chapter-2:music:0")
        assert successor.is_audio_ready
        assert successor.track_ref == staged.fast_track.track_ref
        assert successor.title == staged.fast_track.canonical_title
        assert successor.artist == staged.fast_track.canonical_artist
        assert during_planning.progressive_session is None
        assert during_planning.has_ready_successor is True
        assert task.done() is False

        staged.release.set()
        completed = await task
        assert completed.progressive_session is not None
        locked = completed.progressive_session.chapters[0].resolved_track
        assert locked == staged.fast_track
        assert completed.segment("chapter-2:music:0").track_ref == staged.fast_track.track_ref

    asyncio.run(run())

    assert staged.fast_calls == 1
    assert staged.prepare_calls == 1


class _RejectBootstrapRuntime(_FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.fast_calls = 0
        self.fast_track = ResolvedTrack(
            track_ref="mock:already-ready",
            canonical_artist="Already Artist",
            canonical_title="Already Ready",
        )

    async def prepare_fast_successor(self, episode):
        del episode
        self.fast_calls += 1
        raise AssertionError("existing ready successor must skip FastStart bootstrap")

    async def prepare_session(self, episode):
        del episode
        self.prepare_calls += 1
        base = _session()
        return base.model_copy(
            update={
                "opening_track_ref": "mock:opening",
                "chapters": [
                    base.chapters[0].model_copy(
                        update={"resolved_track": self.fast_track}
                    ),
                    base.chapters[1],
                ],
            }
        )


def test_existing_ready_successor_skips_duplicate_fast_bootstrap() -> None:
    staged = _RejectBootstrapRuntime()
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(repository, progressive_runtime=staged)
    episode = runtime.start(_seed())
    snapshot = runtime.capture_generation_snapshot(episode.id)
    runtime.append_generated_chapter(
        episode.id,
        GeneratedChapter(
            chapter_id="chapter-2",
            segments=[
                MusicSegment(
                    id="chapter-2:music:0",
                    chapter_id="chapter-2",
                    order=1,
                    state=SegmentState.AUDIO_READY,
                    planned_duration_seconds=180,
                    actual_duration_seconds=180,
                    track_ref=staged.fast_track.track_ref,
                    audio_source_url="/api/audio/mock/already-ready",
                    title=staged.fast_track.canonical_title,
                    artist=staged.fast_track.canonical_artist,
                )
            ],
        ),
        snapshot,
    )

    buffered = asyncio.run(
        runtime.ensure_buffer_async(
            episode.id,
            target_chapters=1,
            target_ahead_seconds=300,
        )
    )

    assert staged.fast_calls == 0
    assert staged.prepare_calls == 1
    assert buffered.progressive_session is not None
    assert buffered.progressive_session.chapters[0].resolved_track == staged.fast_track
    assert [
        segment.id
        for segment in buffered.ordered_segments
        if segment.chapter_id == "chapter-2"
    ] == ["chapter-2:music:0"]


class _DeferredPlanningRuntime(_BootstrapRuntime):
    async def prepare_session(self, episode):
        del episode
        self.prepare_calls += 1
        raise ProgressivePlanningDeferred(
            "synthetic full planning deferral behind ready successor"
        )


def test_planning_deferral_keeps_ready_successor_and_allows_later_retry() -> None:
    staged = _DeferredPlanningRuntime()
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(repository, progressive_runtime=staged)
    episode = runtime.start(_seed())

    first = asyncio.run(
        runtime.ensure_buffer_async(
            episode.id,
            target_chapters=2,
            target_ahead_seconds=300,
        )
    )

    assert first.progressive_session is None
    assert first.segment("chapter-2:music:0").is_audio_ready
    assert first.has_ready_successor is True
    assert staged.fast_calls == 1
    assert staged.prepare_calls == 1

    playing_successor = runtime.complete_current_segment(episode.id)
    assert playing_successor.current_segment_id == "chapter-2:music:0"
    assert playing_successor.segment("chapter-2:music:0").is_committed

    retried = asyncio.run(
        runtime.ensure_buffer_async(
            episode.id,
            target_chapters=1,
            target_ahead_seconds=300,
        )
    )

    assert retried.progressive_session is None
    assert staged.fast_calls == 1
    assert staged.prepare_calls == 2
    assert [
        segment.id
        for segment in retried.ordered_segments
        if segment.chapter_id == "chapter-2"
    ] == ["chapter-2:music:0"]


def test_full_generation_never_accepts_progressive_planning_deferral() -> None:
    staged = _DeferredPlanningRuntime()
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(repository, progressive_runtime=staged)
    episode = runtime.start(_seed())
    runtime.request_full_generation(episode.id)

    with pytest.raises(EpisodeRuntimeError, match="cannot defer"):
        asyncio.run(runtime.materialize_all_async(episode.id))

def test_heartbeat_during_staged_preparation_does_not_stale_attach() -> None:
    staged = _FakeRuntime(gated=True)
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(repository, progressive_runtime=staged)
    episode = runtime.start(_seed())

    async def run() -> None:
        task = asyncio.create_task(
            runtime.ensure_buffer_async(
                episode.id,
                target_chapters=1,
                target_ahead_seconds=300,
            )
        )
        await staged.started.wait()
        runtime.heartbeat(episode.id)
        staged.release.set()
        await task

    asyncio.run(run())

    restored = repository.get(episode.id)
    assert staged.prepare_calls == 1
    assert restored.progressive_session is not None
    assert restored.segment("chapter-2:music").is_audio_ready


def test_leave_during_staged_preparation_discards_session() -> None:
    staged = _FakeRuntime(gated=True)
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(repository, progressive_runtime=staged)
    episode = runtime.start(_seed())

    async def run() -> None:
        task = asyncio.create_task(
            runtime.ensure_buffer_async(
                episode.id,
                target_chapters=1,
                target_ahead_seconds=300,
            )
        )
        await staged.started.wait()
        runtime.leave(episode.id)
        staged.release.set()
        with pytest.raises(EpisodeRuntimeError, match="inactive"):
            await task

    asyncio.run(run())

    restored = repository.get(episode.id)
    assert restored.progressive_session is None
    assert [segment.chapter_id for segment in restored.segments] == ["chapter-1"]


def test_generation_failure_keeps_durable_session_for_next_attempt() -> None:
    staged = _FakeRuntime(fail_first_generation=True)
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(repository, progressive_runtime=staged)
    episode = runtime.start(_seed())

    with pytest.raises(RuntimeError, match="synthetic writer failure"):
        asyncio.run(
            runtime.ensure_buffer_async(
                episode.id,
                target_chapters=1,
                target_ahead_seconds=300,
            )
        )

    failed = repository.get(episode.id)
    assert failed.progressive_session is not None
    assert [segment.chapter_id for segment in failed.segments] == ["chapter-1"]

    recovered = asyncio.run(
        runtime.ensure_buffer_async(
            episode.id,
            target_chapters=1,
            target_ahead_seconds=300,
        )
    )
    assert staged.prepare_calls == 1
    assert recovered.segment("chapter-2:music").is_audio_ready


def test_materialize_all_drains_the_staged_route() -> None:
    staged = _FakeRuntime()
    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(repository, progressive_runtime=staged)
    episode = runtime.start(_seed())

    materialized = asyncio.run(runtime.materialize_all_async(episode.id))

    assert materialized.state is EpisodeState.MATERIALIZED
    assert staged.prepare_calls == 1
    assert staged.create_calls >= 1
    assert {segment.chapter_id for segment in materialized.segments} == {
        "chapter-1",
        "chapter-2",
        "chapter-3",
    }
