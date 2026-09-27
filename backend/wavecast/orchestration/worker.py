"""Durable background execution for Streaming Runtime v2 generation jobs."""

from __future__ import annotations

import asyncio
import re
from enum import StrEnum
from typing import Protocol

from wavecast.assembly import EpisodeAssemblyError
from wavecast.models.episode import EpisodeState, LiveEpisode
from wavecast.orchestration.episode import (
    DEFAULT_BUFFER_AHEAD_SECONDS,
    EpisodeRuntimeError,
)
from wavecast.providers.errors import ProviderError, is_retryable
from wavecast.storage.episodes import EpisodeConcurrencyError
from wavecast.storage.generation_jobs import (
    GenerationJob,
    GenerationJobLeaseError,
    GenerationJobMode,
    GenerationJobRepository,
)


class GenerationRuntime(Protocol):
    def get(self, episode_id: str) -> LiveEpisode: ...

    async def ensure_buffer_async(
        self,
        episode_id: str,
        *,
        target_chapters: int = 2,
        target_ahead_seconds: int = DEFAULT_BUFFER_AHEAD_SECONDS,
    ) -> LiveEpisode: ...

    async def materialize_all_async(self, episode_id: str) -> LiveEpisode: ...


class GenerationWorkerAction(StrEnum):
    IDLE = "IDLE"
    COMPLETED = "COMPLETED"
    RETRIED = "RETRIED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class GenerationWorker:
    """Claim and execute one durable generation job at a time.

    The queue owns durable coordination. The worker owns only a bounded lease and
    may disappear at any point; another process can reclaim an expired lease.
    """

    def __init__(
        self,
        jobs: GenerationJobRepository,
        runtime: GenerationRuntime,
        *,
        worker_id: str,
        lease_seconds: int = 120,
        lease_renew_interval_seconds: float = 30.0,
        max_attempts: int = 2,
        base_retry_delay_seconds: int = 5,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if not 0 < lease_renew_interval_seconds < lease_seconds:
            raise ValueError("lease renew interval must be positive and shorter than lease")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if base_retry_delay_seconds < 0:
            raise ValueError("base retry delay must be non-negative")
        self.jobs = jobs
        self.runtime = runtime
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.lease_renew_interval_seconds = lease_renew_interval_seconds
        self.max_attempts = max_attempts
        self.base_retry_delay_seconds = base_retry_delay_seconds

    async def run_once(self) -> GenerationWorkerAction:
        job = await asyncio.to_thread(
            self.jobs.claim,
            self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if job is None:
            return GenerationWorkerAction.IDLE

        stop_lease = asyncio.Event()
        lease_task = asyncio.create_task(self._renew_lease(job, stop_lease))
        try:
            action = await self._execute(job)
        finally:
            stop_lease.set()
            lease_task.cancel()
            try:
                await lease_task
            except asyncio.CancelledError:
                pass
        return action

    async def _execute(self, job: GenerationJob) -> GenerationWorkerAction:
        try:
            current = await asyncio.to_thread(self.runtime.get, job.episode_id)
            if current.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}:
                return await self._complete(job)
            if job.mode is GenerationJobMode.PROGRESSIVE and not current.is_listener_active:
                await asyncio.to_thread(self.jobs.cancel_for_episode, job.episode_id)
                return GenerationWorkerAction.CANCELLED

            if job.mode is GenerationJobMode.FULL:
                await self.runtime.materialize_all_async(job.episode_id)
            else:
                # Current ensure_buffer semantics may stop on seconds-ahead before
                # producing any future chapter when the opening song is long. Make
                # the seconds target strictly exceed the current ready frontier so
                # one complete successor chapter is prepared. Slice C replaces this
                # compatibility bridge with first-class ready-queue policy.
                force_future_target = max(
                    DEFAULT_BUFFER_AHEAD_SECONDS,
                    current.generated_frontier_seconds + 1,
                )
                await self.runtime.ensure_buffer_async(
                    job.episode_id,
                    target_chapters=1,
                    target_ahead_seconds=force_future_target,
                )
            return await self._complete(job)
        except GenerationJobLeaseError:
            return GenerationWorkerAction.SUPERSEDED
        except EpisodeConcurrencyError:
            return await self._retry_or_fail(job, "episode_concurrency", retryable=True)
        except EpisodeAssemblyError as error:
            return await self._retry_or_fail(
                job,
                _assembly_error_code(error),
                retryable=True,
            )
        except ProviderError as error:
            return await self._retry_or_fail(
                job,
                _provider_error_code(error),
                retryable=is_retryable(error),
            )
        except EpisodeRuntimeError:
            recovered = await self._safe_get(job.episode_id)
            if recovered is not None and not recovered.is_listener_active:
                await asyncio.to_thread(self.jobs.cancel_for_episode, job.episode_id)
                return GenerationWorkerAction.CANCELLED
            if recovered is not None and recovered.state in {
                EpisodeState.MATERIALIZED,
                EpisodeState.PUBLISHED,
            }:
                return await self._complete(job)
            return await self._retry_or_fail(
                job,
                "episode_runtime_conflict",
                retryable=True,
            )
        except Exception:
            # Keep unexpected implementation details out of durable state/logging
            # contracts. This is terminal until a new explicit request reactivates
            # the Episode job.
            return await self._fail(job, "worker_unexpected_error")

    async def _complete(self, job: GenerationJob) -> GenerationWorkerAction:
        try:
            result = await asyncio.to_thread(
                self.jobs.complete,
                job.id,
                self.worker_id,
                job.request_version,
            )
        except GenerationJobLeaseError:
            return GenerationWorkerAction.SUPERSEDED
        if result.request_version != job.request_version:
            return GenerationWorkerAction.SUPERSEDED
        return GenerationWorkerAction.COMPLETED

    async def _retry_or_fail(
        self,
        job: GenerationJob,
        error_code: str,
        *,
        retryable: bool,
    ) -> GenerationWorkerAction:
        if retryable and job.attempts < self.max_attempts:
            delay = min(
                60,
                self.base_retry_delay_seconds * (2 ** max(0, job.attempts - 1)),
            )
            try:
                result = await asyncio.to_thread(
                    self.jobs.retry,
                    job.id,
                    self.worker_id,
                    job.request_version,
                    error_code=error_code,
                    delay_seconds=delay,
                )
            except GenerationJobLeaseError:
                return GenerationWorkerAction.SUPERSEDED
            if result.request_version != job.request_version:
                return GenerationWorkerAction.SUPERSEDED
            return GenerationWorkerAction.RETRIED
        return await self._fail(job, error_code)

    async def _fail(
        self, job: GenerationJob, error_code: str
    ) -> GenerationWorkerAction:
        try:
            result = await asyncio.to_thread(
                self.jobs.fail,
                job.id,
                self.worker_id,
                job.request_version,
                error_code=error_code,
            )
        except GenerationJobLeaseError:
            return GenerationWorkerAction.SUPERSEDED
        if result.request_version != job.request_version:
            return GenerationWorkerAction.SUPERSEDED
        return GenerationWorkerAction.FAILED

    async def _safe_get(self, episode_id: str) -> LiveEpisode | None:
        try:
            return await asyncio.to_thread(self.runtime.get, episode_id)
        except Exception:
            return None

    async def _renew_lease(self, job: GenerationJob, stop: asyncio.Event) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self.lease_renew_interval_seconds,
                )
                return
            except TimeoutError:
                try:
                    await asyncio.to_thread(
                        self.jobs.renew_lease,
                        job.id,
                        self.worker_id,
                        lease_seconds=self.lease_seconds,
                    )
                except GenerationJobLeaseError:
                    return


def _assembly_error_code(error: EpisodeAssemblyError) -> str:
    if error.reason_code:
        return _safe_code(error.reason_code)
    return _safe_code(f"{error.stage}_failed")


def _provider_error_code(error: ProviderError) -> str:
    name = type(error).__name__
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return _safe_code(name.removesuffix("_error"))


def _safe_code(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")
    return (normalized or "generation_failed")[:64]
