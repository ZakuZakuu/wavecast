"""Background episode generation worker for Streaming Runtime v2.

The worker owns no provider state. Durable job ownership lives in the generation
job repository and durable episode/intelligence state lives in the Episode
repository. This lets the loop restart safely or move to a separate process
without changing Episode semantics.
"""

from __future__ import annotations

import asyncio
import logging
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

logger = logging.getLogger(__name__)

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

        logger.info(
            "generation_job_claimed episode_id=%s mode=%s attempts=%s request_version=%s",
            job.episode_id,
            job.mode.value,
            job.attempts,
            job.request_version,
        )

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
                    logger.info(
                        "generation_job_cancelled episode_id=%s reason=inactive_listener",
                        job.episode_id,
                    )
                else:
                    logger.warning(
                        "generation_job_execution_failed episode_id=%s "
                        "error_code=episode_runtime error_type=%s",
                        job.episode_id,
                        type(error).__name__,
                    )
                    await self._retry_or_fail(
                        job,
                        "episode_runtime",
                        retryable=True,
                    )
            except EpisodeConcurrencyError as error:
                logger.warning(
                    "generation_job_execution_failed episode_id=%s "
                    "error_code=episode_concurrency error_type=%s",
                    job.episode_id,
                    type(error).__name__,
                )
                await self._retry_or_fail(
                    job,
                    "episode_concurrency",
                    retryable=True,
                )
            except ProviderError as error:
                error_code = _provider_error_code(error)
                logger.warning(
                    "generation_job_execution_failed episode_id=%s "
                    "error_code=%s error_type=%s",
                    job.episode_id,
                    error_code,
                    type(error).__name__,
                )
                await self._retry_or_fail(
                    job,
                    error_code,
                    retryable=is_retryable(error),
                )
            except Exception as error:
                # Never persist or log exception text: provider responses, URLs,
                # prompts, or other sensitive implementation details do not belong
                # in durable state or operational diagnostics.
                stage = getattr(error, "stage", None) or "unknown"
                reason_code = getattr(error, "reason_code", None) or "unknown"
                logger.warning(
                    "generation_job_execution_failed episode_id=%s "
                    "error_code=generation_internal error_type=%s stage=%s reason_code=%s",
                    job.episode_id,
                    type(error).__name__,
                    stage,
                    reason_code,
                )
                await self._retry_or_fail(
                    job,
                    "generation_internal",
                    retryable=False,
                )
            else:
                if lease_lost.is_set():
                    enrich_episode_id = None
                else:
                    try:
                        completed = await asyncio.to_thread(
                            self.jobs.complete,
                            job.id,
                            self.worker_id,
                            job.request_version,
                        )
                    except GenerationJobLeaseError:
                        # A newer owner is responsible for terminal state and
                        # optional enrichment. Do not duplicate Writer/TTS work.
                        logger.warning(
                            "generation_job_completion_lease_lost episode_id=%s "
                            "request_version=%s",
                            job.episode_id,
                            job.request_version,
                        )
                        enrich_episode_id = None
                    else:
                        logger.info(
                            "generation_job_completed episode_id=%s mode=%s "
                            "attempts=%s request_version=%s",
                            job.episode_id,
                            completed.mode.value,
                            completed.attempts,
                            completed.request_version,
                        )
        finally:
            renewal_stop.set()
            lease_watch.cancel()
            renewal.cancel()
            if not work.done():
                work.cancel()
            with suppress(asyncio.CancelledError):
                await lease_watch
            with suppress(asyncio.CancelledError):
                await renewal
            with suppress(asyncio.CancelledError, Exception):
                await work
        if enrich_episode_id is not None:
            self._schedule_narration_enrichment(enrich_episode_id)
        return True

    async def _execute_claimed_job(
        self, job: GenerationJob
    ) -> str | None:
        if job.mode is GenerationJobMode.FULL:
            await self.orchestrator.materialize_all_async(job.episode_id)
            return None
        fast_start = getattr(self.orchestrator, "ensure_fast_start_async", None)
        if callable(fast_start):
            await fast_start(job.episode_id)

        first_buffer = await self.orchestrator.ensure_buffer_async(
            job.episode_id,
            target_chapters=1,
            target_ahead_seconds=self.policy.target_ahead_seconds,
        )

        if (
            getattr(first_buffer, "progressive_session", None) is None
            and getattr(self.orchestrator, "progressive_runtime", None) is not None
        ):
            # A ready FastStart successor may outlive a recoverable full-route
            # planning miss. Do not immediately repeat the same expensive
            # intelligence work in this job.
            return job.episode_id

        # The successor is already durable, so Writer may now spend latency on
        # the first A -> B bridge without being on the music-readiness critical
        # path. Keep this inside the generation lease so a completion race
        # cannot duplicate a paid Writer call. TTS remains detached after job
        # completion.
        try:
            await self.orchestrator.author_pending_narration_async(
                job.episode_id,
                max_chapters=1,
            )
        except Exception as error:
            logger.warning(
                "narration_enrichment_failed episode_id=%s stage=first_writer "
                "error_type=%s",
                job.episode_id,
                type(error).__name__,
            )

        if self.policy.target_chapters > 1:
            await self.orchestrator.ensure_buffer_async(
                job.episode_id,
                target_chapters=self.policy.target_chapters,
                target_ahead_seconds=self.policy.target_ahead_seconds,
            )
        # Residual Writer work and all TTS remain detached after completion.
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

    async def _enrich_narration(
        self,
        episode_id: str,
        *,
        max_chapters: int | None = None,
    ) -> None:
        # Music readiness remains the continuity floor. The first Writer slot
        # may already have been authored under the generation lease; residual
        # Writer work and TTS run detached after job completion.
        limit = self.policy.target_chapters if max_chapters is None else max_chapters
        try:
            authored = await self.orchestrator.author_pending_narration_async(
                episode_id,
                max_chapters=limit,
            )
        except Exception as error:
            logger.warning(
                "narration_enrichment_failed episode_id=%s stage=writer error_type=%s",
                episode_id,
                type(error).__name__,
            )
            return

        authored_counts = _narration_state_counts(authored)
        logger.info(
            "narration_enrichment_stage episode_id=%s stage=writer "
            "script_ready=%s audio_ready=%s skipped=%s authored_chapters=%s",
            episode_id,
            authored_counts["SCRIPT_READY"],
            authored_counts["AUDIO_READY"],
            authored_counts["SKIPPED"],
            len(
                authored.progressive_session.narration_authored_chapter_ids
                if authored.progressive_session is not None
                else []
            ),
        )

        try:
            materialized = await self.orchestrator.materialize_pending_narration_async(
                episode_id,
                max_segments=limit,
            )
        except Exception as error:
            logger.warning(
                "narration_enrichment_failed episode_id=%s stage=tts error_type=%s",
                episode_id,
                type(error).__name__,
            )
            return

        materialized_counts = _narration_state_counts(materialized)
        logger.info(
            "narration_enrichment_stage episode_id=%s stage=tts "
            "script_ready=%s audio_ready=%s skipped=%s",
            episode_id,
            materialized_counts["SCRIPT_READY"],
            materialized_counts["AUDIO_READY"],
            materialized_counts["SKIPPED"],
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
            run = asyncio.create_task(self.run_once())
            stop_watch = asyncio.create_task(stop.wait())
            try:
                await asyncio.wait(
                    {run, stop_watch},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stop.is_set() and not run.done():
                    run.cancel()
                    with suppress(asyncio.CancelledError):
                        await run
                    return
                stop_watch.cancel()
                with suppress(asyncio.CancelledError):
                    await stop_watch
                try:
                    worked = await run
                except Exception:
                    # Database availability may transiently affect claim/lease calls.
                    # Durable jobs remain in Postgres and can be claimed later.
                    worked = False
            finally:
                stop_watch.cancel()
                if not run.done():
                    run.cancel()
                with suppress(asyncio.CancelledError):
                    await stop_watch
                with suppress(asyncio.CancelledError, Exception):
                    await run
            if worked:
                continue
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self.policy.idle_sleep_seconds,
                )
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
            try:
                await asyncio.to_thread(
                    self.jobs.retry,
                    job.id,
                    self.worker_id,
                    job.request_version,
                    error_code=error_code,
                    delay_seconds=delay,
                )
            except GenerationJobLeaseError:
                return
            logger.warning(
                "generation_job_retry_scheduled episode_id=%s error_code=%s "
                "attempts=%s request_version=%s delay_seconds=%s",
                job.episode_id,
                error_code,
                job.attempts,
                job.request_version,
                delay,
            )
            return
        if job.mode is GenerationJobMode.FULL:
            with suppress(Exception):
                await asyncio.to_thread(
                    self.orchestrator.abort_full_generation,
                    job.episode_id,
                )
        try:
            await asyncio.to_thread(
                self.jobs.fail,
                job.id,
                self.worker_id,
                job.request_version,
                error_code=error_code,
            )
        except GenerationJobLeaseError:
            return
        logger.warning(
            "generation_job_failed episode_id=%s error_code=%s "
            "attempts=%s request_version=%s",
            job.episode_id,
            error_code,
            job.attempts,
            job.request_version,
        )


def _narration_state_counts(episode: object) -> dict[str, int]:
    counts = {"SCRIPT_READY": 0, "AUDIO_READY": 0, "SKIPPED": 0}
    segments = getattr(episode, "timeline_segments", ())
    for segment in segments:
        if getattr(getattr(segment, "kind", None), "value", None) != "NARRATION":
            continue
        state = getattr(getattr(segment, "state", None), "value", None)
        if state in counts:
            counts[state] += 1
    return counts


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
