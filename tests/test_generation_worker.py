from __future__ import annotations

import asyncio

from wavecast.models.episode import (
    CoverParams,
    EpisodeSeed,
    EpisodeState,
    GenerationMode,
    MusicSegment,
    SegmentState,
)
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
from wavecast.orchestration.generation import (
    DeterministicMockProgressiveGenerator,
    GeneratedChapter,
)
from wavecast.orchestration.runtime import ProgressivePlanningDeferred
from wavecast.orchestration.worker import GenerationWorker
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.storage.generation_jobs import (
    GenerationJobLeaseError,
    GenerationJobMode,
    GenerationJobStatus,
    InMemoryGenerationJobRepository,
)


def _seed(*, opening_seconds: int = 300) -> EpisodeSeed:
    return EpisodeSeed(
        id="worker-seed",
        title="Background generation",
        topic="durable worker",
        short_description="worker fixture",
        estimated_duration_seconds=1200,
        opening_track_ref="mock:opening",
        opening_track_title="Immediate opening",
        opening_track_artist="Test Artist",
        opening_track_duration_seconds=opening_seconds,
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
    )


def test_worker_logs_safe_generation_lifecycle(caplog) -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime = EpisodeOrchestrator(
        InMemoryEpisodeRepository(),
        progressive_generator=generator,
    )
    episode = runtime.start(_seed())
    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id)
    worker = GenerationWorker(jobs, runtime, worker_id="worker-observability")
    caplog.set_level("INFO", logger="wavecast.orchestration.worker")

    assert asyncio.run(worker.run_once()) is True

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith(f"generation_job_claimed episode_id={episode.id}")
        for message in messages
    )
    assert any(
        message.startswith(f"generation_job_completed episode_id={episode.id}")
        for message in messages
    )


def test_worker_prioritizes_first_narration_after_one_successor() -> None:
    class _Session:
        narration_authored_chapter_ids: list[str] = []

    class _Episode:
        progressive_session = _Session()
        timeline_segments: list[object] = []

    class RecordingRuntime:
        progressive_runtime = object()

        def __init__(self) -> None:
            self.calls: list[str] = []
            self.episode = _Episode()

        async def ensure_buffer_async(
            self,
            episode_id: str,
            *,
            target_chapters: int = 2,
            target_ahead_seconds: int = 300,
        ):
            del episode_id, target_ahead_seconds
            self.calls.append(f"ensure:{target_chapters}")
            return self.episode

        async def author_pending_narration_async(
            self,
            episode_id: str,
            *,
            max_chapters: int = 2,
        ):
            del episode_id
            self.calls.append(f"author:{max_chapters}")
            return self.episode

        async def materialize_pending_narration_async(
            self,
            episode_id: str,
            *,
            max_segments: int = 2,
        ):
            del episode_id
            self.calls.append(f"tts:{max_segments}")
            return self.episode

    runtime = RecordingRuntime()
    jobs = InMemoryGenerationJobRepository()
    job = jobs.request("episode-priority")
    worker = GenerationWorker(jobs, runtime, worker_id="worker-priority")  # type: ignore[arg-type]

    assert asyncio.run(worker._execute_claimed_job(job)) == "episode-priority"

    assert runtime.calls == [
        "ensure:1",
        "author:1",
        "tts:1",
        "ensure:2",
    ]


def test_worker_prepares_successor_behind_long_opening() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime = EpisodeOrchestrator(
        InMemoryEpisodeRepository(),
        progressive_generator=generator,
    )
    episode = runtime.start(_seed())
    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id)
    worker = GenerationWorker(jobs, runtime, worker_id="worker-a")

    assert asyncio.run(worker.run_once()) is True

    updated = runtime.get(episode.id)
    job = jobs.get_for_episode(episode.id)
    assert generator.calls == 1
    assert updated.segment("segment-narration-1").is_audio_ready
    assert updated.segment("segment-bridge").is_audio_ready
    assert job is not None
    assert job.status is GenerationJobStatus.COMPLETED


def test_narration_enrichment_failure_does_not_fail_ready_music_job() -> None:
    class NarrationFailingRuntime(EpisodeOrchestrator):
        async def materialize_pending_narration_async(
            self,
            episode_id: str,
            *,
            max_segments: int = 2,
        ):
            del episode_id, max_segments
            raise RuntimeError("synthetic narration enrichment failure")

    generator = DeterministicMockProgressiveGenerator()
    runtime = NarrationFailingRuntime(
        InMemoryEpisodeRepository(),
        progressive_generator=generator,
    )
    episode = runtime.start(_seed())
    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id)
    worker = GenerationWorker(jobs, runtime, worker_id="worker-narration-failure")

    assert asyncio.run(worker.run_once()) is True

    updated = runtime.get(episode.id)
    job = jobs.get_for_episode(episode.id)
    assert updated.segment("segment-bridge").is_audio_ready
    assert job is not None
    assert job.status is GenerationJobStatus.COMPLETED


def test_progressive_job_completes_while_narration_enrichment_is_still_running() -> None:
    class GatedNarrationRuntime(EpisodeOrchestrator):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            self.narration_started = asyncio.Event()
            self.release_narration = asyncio.Event()

        async def materialize_pending_narration_async(
            self,
            episode_id: str,
            *,
            max_segments: int = 2,
        ):
            del max_segments
            self.narration_started.set()
            await self.release_narration.wait()
            return self.get(episode_id)

    generator = DeterministicMockProgressiveGenerator()
    runtime = GatedNarrationRuntime(
        InMemoryEpisodeRepository(),
        progressive_generator=generator,
    )
    episode = runtime.start(_seed())
    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id)
    worker = GenerationWorker(jobs, runtime, worker_id="worker-gated-narration")

    async def run() -> None:
        assert await worker.run_once() is True
        await runtime.narration_started.wait()

        job = jobs.get_for_episode(episode.id)
        assert job is not None
        assert job.status is GenerationJobStatus.COMPLETED
        assert runtime.get(episode.id).segment("segment-bridge").is_audio_ready

        runtime.release_narration.set()
        await asyncio.sleep(0)
        await worker.stop_enrichment()

    asyncio.run(run())



def test_worker_completes_when_full_planning_is_deferred_behind_ready_music() -> None:
    class DeferredPlanningRuntime:
        async def prepare_fast_successor(self, episode):
            del episode
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
                        track_ref="mock:fast-successor",
                        audio_source_url="/api/audio/mock/fast-successor",
                        title="Fast Successor",
                        artist="Fast Artist",
                    )
                ],
            )

        async def prepare_session(self, episode):
            del episode
            raise ProgressivePlanningDeferred("synthetic deferred planning")

        def create_generator(self, session):
            raise AssertionError("deferred planning must return before chapter generation")

    repository = InMemoryEpisodeRepository()
    runtime = EpisodeOrchestrator(
        repository,
        progressive_runtime=DeferredPlanningRuntime(),  # type: ignore[arg-type]
    )
    episode = runtime.start(_seed())
    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id)
    worker = GenerationWorker(jobs, runtime, worker_id="worker-fast-bootstrap")

    assert asyncio.run(worker.run_once()) is True

    updated = runtime.get(episode.id)
    job = jobs.get_for_episode(episode.id)
    assert updated.progressive_session is None
    assert updated.segment("chapter-2:music:0").is_audio_ready
    assert job is not None
    assert job.status is GenerationJobStatus.COMPLETED

def test_worker_cancels_generation_for_inactive_listener() -> None:
    runtime = EpisodeOrchestrator(InMemoryEpisodeRepository())
    episode = runtime.start(_seed())
    runtime.leave(episode.id)
    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id)
    worker = GenerationWorker(jobs, runtime, worker_id="worker-a")

    assert asyncio.run(worker.run_once()) is True

    job = jobs.get_for_episode(episode.id)
    assert job is not None
    assert job.status is GenerationJobStatus.CANCELLED


def test_full_generation_continues_after_listener_leaves() -> None:
    runtime = EpisodeOrchestrator(
        InMemoryEpisodeRepository(),
        progressive_generator=DeterministicMockProgressiveGenerator(),
    )
    episode = runtime.start(_seed())
    runtime.request_full_generation(episode.id)
    runtime.leave(episode.id)

    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id, GenerationJobMode.FULL)
    worker = GenerationWorker(jobs, runtime, worker_id="worker-full")

    assert asyncio.run(worker.run_once()) is True

    updated = runtime.get(episode.id)
    job = jobs.get_for_episode(episode.id)
    assert updated.state is EpisodeState.MATERIALIZED
    assert updated.generation_mode is GenerationMode.FULL
    assert updated.id == episode.id
    assert job is not None
    assert job.status is GenerationJobStatus.COMPLETED


def test_terminal_full_generation_failure_restores_progressive_episode() -> None:
    class FullFailingRuntime(EpisodeOrchestrator):
        async def materialize_all_async(self, episode_id: str):
            del episode_id
            raise ProviderConfigurationError("secret provider detail must not persist")

    runtime = FullFailingRuntime(InMemoryEpisodeRepository())
    episode = runtime.start(_seed())
    runtime.request_full_generation(episode.id)

    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id, GenerationJobMode.FULL)
    worker = GenerationWorker(jobs, runtime, worker_id="worker-full-failure")

    assert asyncio.run(worker.run_once()) is True

    updated = runtime.get(episode.id)
    job = jobs.get_for_episode(episode.id)
    assert updated.state is EpisodeState.STREAMING
    assert updated.generation_mode is GenerationMode.PROGRESSIVE
    assert job is not None
    assert job.status is GenerationJobStatus.FAILED
    assert job.last_error_code == "provider_configuration"


def test_non_retryable_provider_failure_is_sanitized_and_terminal() -> None:
    class ConfigurationFailingRuntime(EpisodeOrchestrator):
        async def ensure_buffer_async(
            self,
            episode_id: str,
            *,
            target_chapters: int = 2,
            target_ahead_seconds: int = 300,
        ):
            del episode_id, target_chapters, target_ahead_seconds
            raise ProviderConfigurationError("secret provider detail must not persist")

    runtime = ConfigurationFailingRuntime(InMemoryEpisodeRepository())
    jobs = InMemoryGenerationJobRepository()
    jobs.request("episode-provider-failure")
    worker = GenerationWorker(jobs, runtime, worker_id="worker-a")

    assert asyncio.run(worker.run_once()) is True

    job = jobs.get_for_episode("episode-provider-failure")
    assert job is not None
    assert job.status is GenerationJobStatus.FAILED
    assert job.last_error_code == "provider_configuration"


def test_worker_cancels_inflight_generation_when_lease_is_lost() -> None:
    class SlowRuntime(EpisodeOrchestrator):
        def __init__(self) -> None:
            super().__init__(InMemoryEpisodeRepository())
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def ensure_buffer_async(
            self,
            episode_id: str,
            *,
            target_chapters: int = 2,
            target_ahead_seconds: int = 300,
        ):
            del episode_id, target_chapters, target_ahead_seconds
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    class LeaseLosingWorker(GenerationWorker):
        async def _renew_lease(self, job, stop, lease_lost) -> None:
            del job, stop
            await runtime.started.wait()
            lease_lost.set()

    runtime = SlowRuntime()
    jobs = InMemoryGenerationJobRepository()
    jobs.request("episode-lease-loss")
    worker = LeaseLosingWorker(jobs, runtime, worker_id="worker-lease-loss")

    assert asyncio.run(worker.run_once()) is True

    job = jobs.get_for_episode("episode-lease-loss")
    assert runtime.cancelled.is_set()
    assert job is not None
    assert job.status is GenerationJobStatus.RUNNING


def test_external_worker_cancellation_does_not_leave_generation_running() -> None:
    class SlowRuntime(EpisodeOrchestrator):
        def __init__(self) -> None:
            super().__init__(InMemoryEpisodeRepository())
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def ensure_buffer_async(
            self,
            episode_id: str,
            *,
            target_chapters: int = 2,
            target_ahead_seconds: int = 300,
        ):
            del episode_id, target_chapters, target_ahead_seconds
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    runtime = SlowRuntime()
    jobs = InMemoryGenerationJobRepository()
    jobs.request("episode-worker-stop")
    worker = GenerationWorker(jobs, runtime, worker_id="worker-stop")

    async def run() -> None:
        task = asyncio.create_task(worker.run_once())
        await runtime.started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
        assert runtime.cancelled.is_set()

    asyncio.run(run())


def test_completion_lease_loss_does_not_start_duplicate_narration_enrichment() -> None:
    class CompletionLeaseLostRepository(InMemoryGenerationJobRepository):
        def complete(
            self,
            job_id: str,
            worker_id: str,
            request_version: int,
        ):
            del job_id, worker_id, request_version
            raise GenerationJobLeaseError("lease moved to another worker")

    class CountingRuntime(EpisodeOrchestrator):
        def __init__(self) -> None:
            super().__init__(
                InMemoryEpisodeRepository(),
                progressive_generator=DeterministicMockProgressiveGenerator(),
            )
            self.author_calls = 0
            self.materialize_calls = 0

        async def author_pending_narration_async(
            self,
            episode_id: str,
            *,
            max_chapters: int = 2,
        ):
            del max_chapters
            self.author_calls += 1
            return self.get(episode_id)

        async def materialize_pending_narration_async(
            self,
            episode_id: str,
            *,
            max_segments: int = 2,
        ):
            del max_segments
            self.materialize_calls += 1
            return self.get(episode_id)

    runtime = CountingRuntime()
    episode = runtime.start(_seed())
    jobs = CompletionLeaseLostRepository()
    jobs.request(episode.id)
    worker = GenerationWorker(jobs, runtime, worker_id="worker-complete-race")

    async def run() -> None:
        assert await worker.run_once() is True
        await asyncio.sleep(0)
        assert runtime.author_calls == 0
        assert runtime.materialize_calls == 0
        await worker.stop_enrichment()

    asyncio.run(run())


def test_worker_serve_stop_cancels_inflight_generation() -> None:
    class SlowRuntime(EpisodeOrchestrator):
        def __init__(self) -> None:
            super().__init__(InMemoryEpisodeRepository())
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def ensure_buffer_async(
            self,
            episode_id: str,
            *,
            target_chapters: int = 2,
            target_ahead_seconds: int = 300,
        ):
            del episode_id, target_chapters, target_ahead_seconds
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    runtime = SlowRuntime()
    jobs = InMemoryGenerationJobRepository()
    jobs.request("episode-serve-stop")
    worker = GenerationWorker(jobs, runtime, worker_id="worker-serve-stop")

    async def run() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(worker.serve(stop))
        await runtime.started.wait()
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        assert runtime.cancelled.is_set()

    asyncio.run(run())
