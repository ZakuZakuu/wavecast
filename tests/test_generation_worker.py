from __future__ import annotations

import asyncio

from wavecast.assembly import EpisodeAssemblyError
from wavecast.models.episode import CoverParams, EpisodeSeed, EpisodeState, LiveEpisode
from wavecast.orchestration import EpisodeOrchestrator
from wavecast.orchestration.worker import GenerationWorker, GenerationWorkerAction
from wavecast.storage.generation_jobs import (
    GenerationJobMode,
    GenerationJobStatus,
    InMemoryGenerationJobRepository,
)
from wavecast.storage.episodes import InMemoryEpisodeRepository


def seed() -> EpisodeSeed:
    return EpisodeSeed(
        id="worker-seed",
        title="Worker test",
        topic="worker test topic",
        short_description="worker test",
        estimated_duration_seconds=600,
        opening_track_ref="mock:opening",
        opening_track_title="Neon First Light",
        opening_track_artist="Mira Fields",
        opening_track_duration_seconds=22,
        cover=CoverParams(
            family="editorial",
            seed=1,
            palette=("#000000", "#ffffff"),
        ),
    )


def test_progressive_job_materializes_one_ready_successor() -> None:
    runtime = EpisodeOrchestrator(InMemoryEpisodeRepository())
    episode = runtime.start(seed())
    jobs = InMemoryGenerationJobRepository()
    requested = jobs.request(episode.id)

    action = asyncio.run(
        GenerationWorker(
            jobs,
            runtime,
            worker_id="worker-a",
            lease_seconds=30,
            lease_renew_interval_seconds=5,
        ).run_once()
    )

    assert action is GenerationWorkerAction.COMPLETED
    assert jobs.get_for_episode(episode.id).status is GenerationJobStatus.COMPLETED
    updated = runtime.get(episode.id)
    assert updated.generated_frontier_seconds > episode.generated_frontier_seconds
    assert any(segment.chapter_id != "chapter-1" for segment in updated.timeline_segments)
    assert requested.request_version == 1


def test_progressive_job_cancels_when_listener_left() -> None:
    runtime = EpisodeOrchestrator(InMemoryEpisodeRepository())
    episode = runtime.start(seed())
    runtime.leave(episode.id)
    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id)

    action = asyncio.run(
        GenerationWorker(
            jobs,
            runtime,
            worker_id="worker-a",
            lease_seconds=30,
            lease_renew_interval_seconds=5,
        ).run_once()
    )

    assert action is GenerationWorkerAction.CANCELLED
    assert jobs.get_for_episode(episode.id).status is GenerationJobStatus.CANCELLED


def test_full_job_materializes_same_episode() -> None:
    runtime = EpisodeOrchestrator(InMemoryEpisodeRepository())
    episode = runtime.start(seed())
    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id, GenerationJobMode.FULL)

    action = asyncio.run(
        GenerationWorker(
            jobs,
            runtime,
            worker_id="worker-a",
            lease_seconds=30,
            lease_renew_interval_seconds=5,
        ).run_once()
    )

    assert action is GenerationWorkerAction.COMPLETED
    updated = runtime.get(episode.id)
    assert updated.id == episode.id
    assert updated.state is EpisodeState.MATERIALIZED


class FailingRuntime:
    def __init__(self, episode: LiveEpisode) -> None:
        self.episode = episode
        self.calls = 0

    def get(self, episode_id: str) -> LiveEpisode:
        assert episode_id == self.episode.id
        return self.episode.model_copy(deep=True)

    async def ensure_buffer_async(
        self,
        episode_id: str,
        *,
        target_chapters: int = 2,
        target_ahead_seconds: int = 300,
    ) -> LiveEpisode:
        del episode_id, target_chapters, target_ahead_seconds
        self.calls += 1
        raise EpisodeAssemblyError(
            "provider payload was invalid",
            stage="writer",
            reason_code="writer_normalization_failed",
        )

    async def materialize_all_async(self, episode_id: str) -> LiveEpisode:
        del episode_id
        raise AssertionError("full generation was not requested")


def test_assembly_failure_retries_once_then_becomes_failed() -> None:
    runtime_base = EpisodeOrchestrator(InMemoryEpisodeRepository())
    episode = runtime_base.start(seed())
    runtime = FailingRuntime(episode)
    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id)
    worker = GenerationWorker(
        jobs,
        runtime,
        worker_id="worker-a",
        lease_seconds=30,
        lease_renew_interval_seconds=5,
        max_attempts=2,
        base_retry_delay_seconds=0,
    )

    first = asyncio.run(worker.run_once())
    after_first = jobs.get_for_episode(episode.id)

    assert first is GenerationWorkerAction.RETRIED
    assert after_first is not None
    assert after_first.status is GenerationJobStatus.PENDING
    assert after_first.last_error_code == "writer_normalization_failed"

    second = asyncio.run(worker.run_once())
    after_second = jobs.get_for_episode(episode.id)

    assert second is GenerationWorkerAction.FAILED
    assert after_second is not None
    assert after_second.status is GenerationJobStatus.FAILED
    assert after_second.last_error_code == "writer_normalization_failed"
    assert runtime.calls == 2


def test_failed_job_can_be_reactivated_by_explicit_request() -> None:
    runtime_base = EpisodeOrchestrator(InMemoryEpisodeRepository())
    episode = runtime_base.start(seed())
    runtime = FailingRuntime(episode)
    jobs = InMemoryGenerationJobRepository()
    jobs.request(episode.id)
    worker = GenerationWorker(
        jobs,
        runtime,
        worker_id="worker-a",
        lease_seconds=30,
        lease_renew_interval_seconds=5,
        max_attempts=1,
        base_retry_delay_seconds=0,
    )

    assert asyncio.run(worker.run_once()) is GenerationWorkerAction.FAILED
    failed = jobs.get_for_episode(episode.id)
    assert failed is not None

    reactivated = jobs.request(episode.id)

    assert reactivated.id == failed.id
    assert reactivated.status is GenerationJobStatus.PENDING
    assert reactivated.request_version == failed.request_version + 1
    assert reactivated.last_error_code is None
