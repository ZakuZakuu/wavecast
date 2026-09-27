from __future__ import annotations

import asyncio

from wavecast.models.episode import CoverParams, EpisodeSeed, EpisodeState, GenerationMode
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
from wavecast.orchestration.generation import DeterministicMockProgressiveGenerator
from wavecast.orchestration.worker import GenerationWorker
from wavecast.providers.errors import ProviderConfigurationError
from wavecast.storage.generation_jobs import (
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
