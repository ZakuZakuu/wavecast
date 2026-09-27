"""Background episode generation worker for Streaming Runtime v2.

The worker owns no provider state. Durable job ownership lives in the generation
job repository and durable episode/intelligence state lives in the Episode
repository. This lets the loop restart safely or move to a separate process
without changing Episode semantics.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Final

from wavecast.orchestration.episode import EpisodeOrchestrator, EpisodeRuntimeError
from wavecast.providers.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    is_retryable,
)
from wavecast.storage.episodes import EpisodeConcurrencyError
from wavecast.storage.generation_jobs import (
    GenerationJob,
    GenerationJobLeaseError,
    GenerationJobMode,
    GenerationJobRepository,
)

DEFAULT_READY_AHEAD_SECONDS: Final = 180
DEFAULT_READY_CHAPTERS: Final = 2
DEFAULT_LEASE_SECONDS: Final = 300
DEFAULT_MAX_ATTEMPTS: Final = 3


@dataclass(frozen=True)
class GenerationWorkerPolicy:
    target_chapters: int = DEFAULT_READY_CHAPTERS
    target_ahead_seconds: int = DEFAULT_READY_AHEAD_SECONDS
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    idle_sleep_seconds: float = 0.5

    def __post_init__(self) -> None:
        if self.target_chapters not in {1, 2}:
            raise ValueError("target_chapters must be one or two")
        if self.target_ahead_seconds <= 0:
            raise ValueError("target_ahead_seconds must be positive")
        if self.lease_seconds < 30:
            raise ValueError("lease_seconds must be at least 30")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.idle_sleep_seconds <= 0:
            raise ValueError("idle_sleep_seconds must be positive")


class GenerationWorker:
    """Claim and execute durable Episode generation jobs one at a time."""

    def __init__(
        self,
        jobs: GenerationJobRepository,
        orchestrator: EpisodeOrchestrator,
        *,
        worker_id: str,
        policy: GenerationWorkerPolicy | None = None,
    ) -> None:
        normalized = worker_id.strip()
        if not normalized:
            raise ValueError("worker_id cannot be blank")
        self.jobs = jobs
        self.orchestrator = orchestrator
        self.worker_id = normalized
        self.policy = policy or GenerationWorkerPolicy()
        self._enrichment_tasks: set[asyncio.Task[None]] = set()
        self._enrichment_episode_ids: set[str] = set()

    async def run_once(self) -> bool:
        job = await asyncio.to_thread(
            self.jobs.claim,
            self.worker_id,
            lease_seconds=self.policy.lease_seconds,
        )
        if job is None:
            return False

        renewal_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        renewal = asyncio.create_task(
            self._renew_lease(job, renewal_stop, lease_lost)
        )
        work = asyncio.create_task(self._execute_claimed_job(job))
        lease_watch = asyncio.create_task(lease_lost.wait())
        enrich_episode_id: str | None = None
        try:
            await asyncio.wait(
                {work, lease_watch},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if lease_lost.is_set():
                # Ownership is no longer trustworthy. Stop expensive provider
                # work and leave terminal job mutation to the current lease owner.
                if not work.done():
                    work.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await work
                return True

            lease_watch.cancel()
            with suppress(asyncio.CancelledError):
                await lease_watch
            try:
                enrich_episode_id = await work
            except EpisodeRuntimeError as error:
                if (
                    job.mode is GenerationJobMode.PROGRESSIVE
                    and "inactive" in str(error).casefold()
                ):
                    await asyncio.to_thread(
                        self.jobs.cancel_for_episode,
                        job.episode_id,
                    )
                else:
                    await self._retry_or_fail(
                        job,
                        "episode_runtime",
                        retryable=True,
                    )
            except EpisodeConcurrencyError:
                await self._retry_or_fail(
                    job,
                    "episode_concurrency",
                    retryable=True,
                )
            except ProviderError as error:
                await self._retry_or_fail(
                    job,
                    _provider_error_code(error),
                    retryable=is_retryable(error),
                )
            except Exception:
                # Never persist exception text: provider responses, URLs, or other
                # sensitive implementation details do not belong in durable job state.
                await self._retry_or_fail(
                    job,
                    "generation_internal",
                    retryable=False,
                )
            else:
                with suppress(GenerationJobLeaseError):
                    await asyncio.to_thread(
                        self.jobs.complete,
                        job.id,
                        self.worker_id,
                        job.request_version,
                    )
        finally:
            renewal_stop.set()
            lease_watch.cancel()
            renewal.cancel()
            with suppress(asyncio.CancelledError):
                await lease_watch
            with suppress(asyncio.CancelledError):
                await renewal
        if enrich_episode_id is not None:
            self._schedule_narration_enrichment(enrich_episode_id)
        return True

    async def _execute_claimed_job(
        self, job: GenerationJob
    ) -> str | None:
        if job.mode is GenerationJobMode.FULL:
            await self.orchestrator.materialize_all_async(job.episode_id)
            return None
        await self.orchestrator.ensure_buffer_async(
            job.episode_id,
            target_chapters=self.policy.target_chapters,
            target_ahead_seconds=self.policy.target_ahead_seconds,
        )
        # Music readiness is the durable success boundary. Narration enrichment
        # is scheduled only after the generation job is completed, so slow TTS
        # cannot hold the refill channel RUNNING.
        return job.episode_id

    def _schedule_narration_enrichment(self, episode_id: str) -> None:
        if episode_id in self._enrichment_episode_ids:
            return
        self._enrichment_episode_ids.add(episode_id)
        task = asyncio.create_task(self._enrich_narration(episode_id))
        self._enrichment_tasks.add(task)

        def _done(completed: asyncio.Task[None]) -> None:
            self._enrichment_tasks.discard(completed)
            self._enrichment_episode_ids.discard(episode_id)

        task.add_done_callback(_done)

    async def _enrich_narration(self, episode_id: str) -> None:
        # Music readiness is already durable before this optional task starts.
        # Writer creates SCRIPT_READY narration first; TTS enriches it only if
        # the chapter is still speculative. Process loss may omit narration but
        # cannot lose music or rewrite exposed playback history.
        with suppress(Exception):
            await self.orchestrator.author_pending_narration_async(
                episode_id,
                max_chapters=self.policy.target_chapters,
            )
            await self.orchestrator.materialize_pending_narration_async(
                episode_id,
                max_segments=self.policy.target_chapters,
            )

    async def stop_enrichment(self) -> None:
        tasks = list(self._enrichment_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._enrichment_tasks.clear()
        self._enrichment_episode_ids.clear()

    async def serve(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                worked = await self.run_once()
            except Exception:
                # Database availability may transiently affect claim/lease calls.
                # Durable jobs remain in Postgres and can be claimed later.
                worked = False
            if worked:
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.policy.idle_sleep_seconds)
            except TimeoutError:
                pass

    async def _renew_lease(
        self,
        job: GenerationJob,
        stop: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        interval = max(10.0, self.policy.lease_seconds / 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                await asyncio.to_thread(
                    self.jobs.renew_lease,
                    job.id,
                    self.worker_id,
                    lease_seconds=self.policy.lease_seconds,
                )
            except Exception:
                # If ownership cannot be renewed or verified, fail closed.
                # Continuing provider work after an uncertain lease risks
                # duplicate paid work after another worker reclaims the job.
                lease_lost.set()
                return

    async def _retry_or_fail(
        self,
        job: GenerationJob,
        error_code: str,
        *,
        retryable: bool,
    ) -> None:
        if retryable and job.attempts < self.policy.max_attempts:
            delay = min(60, 5 * (2 ** max(0, job.attempts - 1)))
            with suppress(GenerationJobLeaseError):
                await asyncio.to_thread(
                    self.jobs.retry,
                    job.id,
                    self.worker_id,
                    job.request_version,
                    error_code=error_code,
                    delay_seconds=delay,
                )
            return
        if job.mode is GenerationJobMode.FULL:
            with suppress(Exception):
                await asyncio.to_thread(
                    self.orchestrator.abort_full_generation,
                    job.episode_id,
                )
        with suppress(GenerationJobLeaseError):
            await asyncio.to_thread(
                self.jobs.fail,
                job.id,
                self.worker_id,
                job.request_version,
                error_code=error_code,
            )


def _provider_error_code(error: ProviderError) -> str:
    if isinstance(error, ProviderConfigurationError):
        return "provider_configuration"
    if isinstance(error, ProviderRateLimitError):
        return "provider_rate_limit"
    if isinstance(error, ProviderTimeoutError):
        return "provider_timeout"
    if isinstance(error, ProviderUnavailableError):
        return "provider_unavailable"
    if isinstance(error, ProviderInvalidResponseError):
        return "provider_invalid_response"
    return "provider_error"
